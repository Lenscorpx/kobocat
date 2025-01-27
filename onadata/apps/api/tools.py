# coding: utf-8
import inspect
import os
import re
import time
from datetime import datetime

import rest_framework.views as rest_framework_views
from django import forms
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.files.storage import get_storage_class
from django.http import HttpResponseNotFound
from django.http import HttpResponseRedirect
from django.utils.translation import ugettext as _
from rest_framework import exceptions
from taggit.forms import TagField

from onadata.apps.main.forms import QuickConverterForm
from onadata.apps.main.models import UserProfile
from onadata.apps.viewer.models.parsed_instance import datetime_from_str
from onadata.libs.utils.logger_tools import publish_form
from onadata.libs.utils.logger_tools import response_with_mimetype_and_name
from onadata.libs.utils.user_auth import check_and_set_form_by_id
from onadata.libs.utils.user_auth import check_and_set_form_by_id_string

DECIMAL_PRECISION = 2


def _get_first_last_names(name):
    name_split = name.split()
    first_name = name_split[0]
    last_name = ''
    if len(name_split) > 1:
        last_name = ' '.join(name_split[1:])
    return first_name, last_name


def _get_id_for_type(record, mongo_field):
    date_field = datetime_from_str(record[mongo_field])
    mongo_str = '$' + mongo_field

    return {"$substr": [mongo_str, 0, 10]} if isinstance(date_field, datetime)\
        else mongo_str


def publish_xlsform(request, user, existing_xform=None):
    """
    If `existing_xform` is specified, that form will be overwritten with the
    new XLSForm
    """
    if not request.user.has_perm(
        'can_add_xform',
        UserProfile.objects.get_or_create(user=user)[0]
    ):
        raise exceptions.PermissionDenied(
            detail=_("User %(user)s has no permission to add xforms to "
                     "account %(account)s" % {'user': request.user.username,
                                              'account': user.username}))
    if existing_xform and not request.user.has_perm(
            'change_xform', existing_xform):
        raise exceptions.PermissionDenied(
            detail=_("User %(user)s has no permission to change this "
                     "form." % {'user': request.user.username, })
        )

    def set_form():
        form = QuickConverterForm(request.POST, request.FILES)
        if existing_xform:
            return form.publish(user, existing_xform.id_string)
        else:
            return form.publish(user)

    return publish_form(set_form)


def get_xform(formid, request, username=None):
    try:
        formid = int(formid)
    except ValueError:
        username = username is None and request.user.username
        xform = check_and_set_form_by_id_string(username, formid, request)
    else:
        xform = check_and_set_form_by_id(int(formid), request)

    if not xform:
        raise exceptions.PermissionDenied(_(
            "You do not have permission to view data from this form."))

    return xform


def get_user_profile_or_none(username):
    profile = None

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        pass
    else:
        profile, created = UserProfile.objects.get_or_create(user=user)

    return profile


def add_tags_to_instance(request, instance):
    class TagForm(forms.Form):
        tags = TagField()

    form = TagForm(request.data)

    if form.is_valid():
        tags = form.cleaned_data.get('tags', None)

        if tags:
            for tag in tags:
                instance.tags.add(tag)
            instance.save()


def add_validation_status_to_instance(request, instance):
    """
    Saves instance validation status if it's valid (belong to XForm/Asset validation statuses)

    :param request: REST framework's Request object
    :param instance: Instance object
    :return: Boolean
    """
    validation_status_uid = request.data.get("validation_status.uid")
    success = False

    # Payload must contain validation_status property.
    if validation_status_uid:

        validation_status = get_validation_status(
            validation_status_uid, instance.asset, request.user.username)
        if validation_status:
            instance.validation_status = validation_status
            instance.save()
            success = instance.parsed_instance.update_mongo(asynchronous=False)

    return success


def get_validation_status(validation_status_uid, asset, username):
    # Validate validation_status value It must belong to asset statuses.
    available_statuses = {status.get("uid"): status
                          for status in asset.settings.get("validation_statuses")}

    validation_status = {}

    if validation_status_uid in available_statuses.keys():
        available_status = available_statuses.get(validation_status_uid)
        validation_status = {
            "timestamp": int(time.time()),
            "uid": validation_status_uid,
            "by_whom": username,
            "color": available_status.get("color"),
            "label": available_status.get("label")
        }

    return validation_status


def remove_validation_status_from_instance(instance):
    instance.validation_status = {}
    instance.save()
    return instance.parsed_instance.update_mongo(asynchronous=False)


def get_media_file_response(metadata):
    if metadata.data_file:
        file_path = metadata.data_file.name
        filename, extension = os.path.splitext(file_path.split('/')[-1])
        extension = extension.strip('.')
        dfs = get_storage_class()()

        if dfs.exists(file_path):
            response = response_with_mimetype_and_name(
                metadata.data_file_type,
                filename, extension=extension, show_date=False,
                file_path=file_path, full_mime=True)

            return response
        else:
            return HttpResponseNotFound()
    else:
        return HttpResponseRedirect(metadata.data_value)


def get_view_name(view_obj):
    """
    Override Django REST framework's name for the base API class
    """
    # The base API class should inherit directly from APIView. We can't use
    # issubclass() because ViewSets also inherit (indirectly) from APIView.
    try:
        if inspect.getmro(view_obj.__class__)[1] is rest_framework_views.APIView:
            return 'KoBo Api'  # awkward capitalization for consistency
    except KeyError:
        pass
    return rest_framework_views.get_view_name(view_obj)


def get_view_description(view_obj, html=False):
    """
    Replace example.com in Django REST framework's default API description
    with the domain name of the current site
    """
    domain = Site.objects.get_current().domain
    description = rest_framework_views.get_view_description(view_obj, html)
    # description might not be a plain string: e.g. it could be a SafeText
    # to prevent further HTML escaping
    original_type = type(description)
    description = original_type(re.sub(
        '(https*)://example.com',
        '\\1://{}'.format(domain),
        description
    ))
    return description
