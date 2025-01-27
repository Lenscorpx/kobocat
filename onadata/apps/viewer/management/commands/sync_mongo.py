#!/usr/bin/env python
# coding: utf-8
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import ugettext_lazy

from onadata.apps.logger.models import XForm
from onadata.libs.utils.logger_tools import mongo_sync_status


class Command(BaseCommand):
    args = '[username] [id_string]'
    help = ugettext_lazy("Check the count of submissions in sqlite vs the "
                         "mongo db per form and optionally run remongo.")

    def add_arguments(self, parser):

        parser.add_argument('username', nargs='?', default=None)
        parser.add_argument('id_string', nargs='?', default=None)

        parser.add_argument('-r', '--remongo',
                            action='store_true',
                            dest='remongo',
                            default=False,
                            help=ugettext_lazy("Whether to run remongo on the "
                                               "found set.")
                            )

        parser.add_argument('-a', '--all',
                            action='store_true', dest='update_all',
                            default=False,
                            help=ugettext_lazy(
                                "Update all instances for the selected "
                                "form(s), including existing ones. "
                                "Will delete and re-create mongo records. "
                                "Only makes sense when used with the -r option")
                            )

    def handle(self, username, id_string, remongo, update_all, *args, **kwargs):
        user = xform = None
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError("User %s does not exist" % username)
        if username and id_string:
            try:
                xform = XForm.objects.get(user=user, id_string=id_string)
            except XForm.DoesNotExist:
                raise CommandError("Xform %s does not exist for user %s" %
                                   (id_string, user.username))

        report_string = mongo_sync_status(remongo, update_all, user, xform)
        self.stdout.write(report_string)
