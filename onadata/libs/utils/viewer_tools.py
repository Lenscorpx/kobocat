# coding: utf-8
import os
import json
import traceback
import requests
import zipfile

from tempfile import NamedTemporaryFile
from xml.dom import minidom

from django.conf import settings
from django.core.files.storage import get_storage_class
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.mail import mail_admins
from django.utils.translation import ugettext as _

from onadata.libs.utils import common_tags


SLASH = "/"


class MyError(Exception):
    pass


class EnketoError(Exception):
    pass


def image_urls_for_form(xform):
    return sum([
        image_urls(s) for s in xform.instances.all()
    ], [])


def get_path(path, suffix):
    fileName, fileExtension = os.path.splitext(path)
    return fileName + suffix + fileExtension


# TODO VERIFY IF STILL USED
def image_urls(instance):
    image_urls_dict_ = image_urls_dict(instance)
    return image_urls_dict_.values()


def image_urls_dict(instance):
    """
    Returns a dict of attachments with keys as base filename
    and values link through `kobocat` redirector.
    Only exposes `suffix` version of it. It will be created on the fly by the
    redirector

    :param instance: Instance
    :return: dict
    """
    urls = dict()
    # Remove leading dash from suffix
    suffix = settings.THUMB_CONF['medium']['suffix'][1:]
    for a in instance.attachments.all():
        urls[a.filename] = a.secure_url(suffix=suffix)
    return urls


def parse_xform_instance(xml_str):
    """
    'xml_str' is a str object holding the XML of an XForm
    instance. Return a python object representation of this XML file.
    """
    xml_obj = minidom.parseString(xml_str)
    root_node = xml_obj.documentElement
    # go through the xml object creating a corresponding python object
    # NOTE: THIS WILL DESTROY ANY DATA COLLECTED WITH REPEATABLE NODES
    # THIS IS OKAY FOR OUR USE CASE, BUT OTHER USERS SHOULD BEWARE.
    survey_data = dict(_path_value_pairs(root_node))
    assert len(list(_all_attributes(root_node))) == 1, \
        _("There should be exactly one attribute in this document.")
    survey_data.update({
        common_tags.XFORM_ID_STRING: root_node.getAttribute("id"),
        common_tags.INSTANCE_DOC_NAME: root_node.nodeName,
    })
    return survey_data


def _path(node):
    n = node
    levels = []
    while n.nodeType != n.DOCUMENT_NODE:
        levels = [n.nodeName] + levels
        n = n.parentNode
    return SLASH.join(levels[1:])


def _path_value_pairs(node):
    """
    Using a depth first traversal of the xml nodes build up a python
    object in parent that holds the tree structure of the data.
    """
    if len(node.childNodes) == 0:
        # there's no data for this leaf node
        yield _path(node), None
    elif len(node.childNodes) == 1 and \
            node.childNodes[0].nodeType == node.TEXT_NODE:
        # there is data for this leaf node
        yield _path(node), node.childNodes[0].nodeValue
    else:
        # this is an internal node
        for child in node.childNodes:
            for pair in _path_value_pairs(child):
                yield pair


def _all_attributes(node):
    """
    Go through an XML document returning all the attributes we see.
    """
    if hasattr(node, "hasAttributes") and node.hasAttributes():
        for key in node.attributes.keys():
            yield key, node.getAttribute(key)
    for child in node.childNodes:
        for pair in _all_attributes(child):
            yield pair


def report_exception(subject, info, exc_info=None):
    if exc_info:
        cls, err = exc_info[:2]
        info += _("Exception in request: %(class)s: %(error)s") \
            % {'class': cls.__name__, 'error': err}
        info += "".join(traceback.format_exception(*exc_info))

    if settings.DEBUG:
        print(subject)
        print(info)
    else:
        mail_admins(subject=subject, message=info)


def django_file(path, field_name, content_type):
    # adapted from here: http://groups.google.com/group/django-users/browse_th\
    # read/thread/834f988876ff3c45/
    f = open(path, 'rb')
    return InMemoryUploadedFile(
        file=f,
        field_name=field_name,
        name=f.name,
        content_type=content_type,
        size=os.path.getsize(path),
        charset=None
    )


def export_def_from_filename(filename):
    # TODO fix circular import and move to top
    from onadata.apps.viewer.models.export import Export
    path, ext = os.path.splitext(filename)
    ext = ext[1:]
    # try get the def from extension
    mime_type = Export.EXPORT_MIMES[ext]
    return ext, mime_type


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def enketo_url(form_url, id_string, instance_xml=None,
               instance_id=None, return_url=None, instance_attachments=None):

    if not hasattr(settings, 'ENKETO_URL')\
            and not hasattr(settings, 'ENKETO_API_SURVEY_PATH'):
        return False

    if instance_attachments is None:
        instance_attachments = {}

    url = settings.ENKETO_URL + settings.ENKETO_API_SURVEY_PATH

    values = {
        'form_id': id_string,
        'server_url': form_url
    }

    if instance_id is not None and instance_xml is not None:
        url = settings.ENKETO_URL + settings.ENKETO_API_INSTANCE_PATH
        values.update({
            'instance': instance_xml,
            'instance_id': instance_id,
            'return_url': return_url
        })
        for key, value in instance_attachments.items():
            values.update({
                'instance_attachments[' + key + ']': value
            })
    req = requests.post(url, data=values,
                        auth=(settings.ENKETO_API_TOKEN, ''), verify=False)

    if req.status_code in [200, 201]:
        try:
            response = req.json()
        except ValueError:
            pass
        else:
            if 'edit_url' in response:
                return response['edit_url']
            if settings.ENKETO_OFFLINE_SURVEYS and ('offline_url' in response):
                return response['offline_url']
            if 'url' in response:
                return response['url']
    else:
        try:
            response = req.json()
        except ValueError:
            pass
        else:
            if 'message' in response:
                raise EnketoError(response['message'])
    return False


def create_attachments_zipfile(attachments, output_file=None):
    if not output_file:
        output_file = NamedTemporaryFile()
    else:
        # Disable seeking in a way understood by Python's zipfile module. See
        # https://github.com/python/cpython/blob/ca2009d72a52a98bf43aafa9ad270a4fcfabfc89/Lib/zipfile.py#L1270-L1274
        # This is a workaround for https://github.com/kobotoolbox/kobocat/issues/475
        # and https://github.com/jschneier/django-storages/issues/566
        def no_seeking(*a, **kw):
            raise AttributeError(
                'Seeking disabled! See '
                'https://github.com/kobotoolbox/kobocat/issues/475'
            )
        output_file.seek = no_seeking

    storage = get_storage_class()()
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_STORED, allowZip64=True) as zip_file:
        for attachment in attachments:
            if storage.exists(attachment.media_file.name):
                try:
                    with storage.open(attachment.media_file.name, 'rb') as source_file:
                        zip_file.writestr(attachment.media_file.name, source_file.read())
                except Exception as e:
                    report_exception("Error adding file \"{}\" to archive.".format(attachment.media_file.name), e)

    return output_file


def _get_form_url(username):
    if settings.TESTING_MODE:
        http_host = 'http://{}'.format(settings.TEST_HTTP_HOST)
        username = settings.TEST_USERNAME
    else:
        # Always use a public url to prevent Enketo SSRF from blocking request
        http_host = settings.KOBOCAT_URL

    # Internal requests use the public url, KOBOCAT_URL already has the protocol
    return '{http_host}/{username}'.format(
        http_host=http_host,
        username=username
    )


def get_enketo_edit_url(request, instance, return_url):
    form_url = _get_form_url(instance.xform.user.username)
    instance_attachments = image_urls_dict(instance)
    url = enketo_url(
        form_url, instance.xform.id_string, instance_xml=instance.xml,
        instance_id=instance.uuid, return_url=return_url,
        instance_attachments=instance_attachments)
    return url
