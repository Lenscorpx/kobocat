# coding: utf-8
import unittest

from django.test import TestCase
from django.test.client import Client
from django.contrib.auth.models import User
from django.urls import reverse

from onadata import koboform
from onadata.apps.main.views import profile


class TestUserProfile(TestCase):

    def setup(self):
        self.client = Client()
        self.assertEqual(len(User.objects.all()), 0)

    def _login_user_and_profile(self, extra_post_data={}):
        post_data = {
            'username': 'bob',
            'email': 'bob@columbia.edu',
            'password1': 'bobbob',
            'password2': 'bobbob',
            'name': 'Bob',
            'city': 'Bobville',
            'country': 'US',
            'organization': 'Bob Inc.',
            'home_page': 'bob.com',
            'twitter': 'boberama'
        }
        url = '/accounts/register/'
        post_data = dict(post_data.items() + extra_post_data.items())
        self.response = self.client.post(url, post_data)
        try:
            self.user = User.objects.get(username=post_data['username'])
        except User.DoesNotExist:
            pass

    @unittest.skip("User creation is deactivated on KC")
    def test_create_user_with_given_name(self):
        self._login_user_and_profile()
        self.assertEqual(self.response.status_code, 302)
        self.assertEqual(self.user.username, 'bob')

    @unittest.skip("User creation is deactivated on KC")
    def test_create_user_profile_for_user(self):
        self._login_user_and_profile()
        self.assertEqual(self.response.status_code, 302)
        user_profile = self.user.profile
        self.assertEqual(user_profile.city, 'Bobville')
        self.assertTrue(hasattr(user_profile, 'metadata'))

    @unittest.skip("User creation is deactivated on KC")
    def test_disallow_non_alpha_numeric(self):
        invalid_usernames = [
            'b ob',
            'b.o.b.',
            'b-ob',
            'b!',
            '@bob',
            'bob@bob.com',
            'bob$',
            'b&o&b',
            'bob?',
            '#bob',
            '(bob)',
            'b*ob',
            '%s % bob',
        ]
        users_before = User.objects.count()
        for username in invalid_usernames:
            self._login_user_and_profile({'username': username})
            self.assertEqual(User.objects.count(), users_before)

    @unittest.skip("User creation is deactivated on KC")
    def test_disallow_reserved_name(self):
        users_before = User.objects.count()
        self._login_user_and_profile({'username': 'admin'})
        self.assertEqual(User.objects.count(), users_before)

    def test_redirect_to_login_if_user_does_not_exist(self):
        response = self.client.get(reverse(profile,
                                           kwargs={'username': 'nonuser'}))
        self.assertEqual(response.status_code, 302)
        login_url = reverse('auth_login')
        if koboform.active and koboform.autoredirect:
            redirect_to = koboform.login_url()
        else:
            redirect_to = login_url
        self.assertEqual(response.url, redirect_to)

    @unittest.skip("We don't use twitter in kobocat tests")
    def test_show_single_at_sign_in_twitter_link(self):
        self._login_user_and_profile()
        response = self.client.get(
            reverse(profile, kwargs={
                'username': "bob"
            }))
        self.assertContains(response, ">@boberama")
        # add the @ sign
        self.user.profile.twitter = "@boberama"
        self.user.profile.save()
        response = self.client.get(
            reverse(profile, kwargs={
                'username': "bob"
            }))
        self.assertContains(response, ">@boberama")
