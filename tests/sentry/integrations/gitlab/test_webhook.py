from __future__ import absolute_import

from sentry.models import (
    Commit,
    CommitAuthor,
    PullRequest
)
from .testutils import (
    GitLabTestCase,
    WEBHOOK_TOKEN,
    EXTERNAL_ID,
    MERGE_REQUEST_OPENED_EVENT,
    PUSH_EVENT,
    PUSH_EVENT_IGNORED_COMMIT
)

import pytest


class WebhookTest(GitLabTestCase):
    url = '/extensions/gitlab/webhook/'

    def test_get(self):
        response = self.client.get(self.url)
        assert response.status_code == 405

    def test_unknown_event(self):
        response = self.client.post(
            self.url,
            data=PUSH_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='lol'
        )
        assert response.status_code == 400

    def test_invalid_token(self):
        response = self.client.post(
            self.url,
            data=PUSH_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN='wrong',
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        assert response.status_code == 400

    def test_valid_id_invalid_secret(self):
        response = self.client.post(
            self.url,
            data=PUSH_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=u'{}:{}'.format(EXTERNAL_ID, 'wrong'),
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        assert response.status_code == 400

    def test_invalid_payload(self):
        response = self.client.post(
            self.url,
            data='lol not json',
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        assert response.status_code == 400

    def test_push_event_missing_repo(self):
        response = self.client.post(
            self.url,
            data=PUSH_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        # Missing repositories don't 40x as we can't explode
        # on missing repositories due to the possibility of multiple
        # organizations sharing an integration and not having the same
        # repositories enabled.
        assert response.status_code == 204

    def test_push_event_multiple_organizations_one_missing_repo(self):
        # Create a repo on the primary organization
        repo = self.create_repo('getsentry/sentry')

        # Second org with no repo.
        other_org = self.create_organization(owner=self.user)
        self.integration.add_organization(other_org, self.user)

        response = self.client.post(
            self.url,
            data=PUSH_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        assert response.status_code == 204
        commits = Commit.objects.all()
        assert len(commits) == 2
        for commit in commits:
            assert commit.organization_id == self.organization.id
            assert commit.repository_id == repo.id

    def test_push_event_multiple_organizations(self):
        # Create a repo on the primary organization
        repo = self.create_repo('getsentry/sentry')

        # Second org with the same repo
        other_org = self.create_organization(owner=self.user)
        self.integration.add_organization(other_org, self.user)
        other_repo = self.create_repo('getsentry/sentry', organization_id=other_org.id)

        response = self.client.post(
            self.url,
            data=PUSH_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        assert response.status_code == 204

        commits = Commit.objects.filter(repository_id=repo.id).all()
        assert len(commits) == 2
        for commit in commits:
            assert commit.organization_id == self.organization.id

        commits = Commit.objects.filter(repository_id=other_repo.id).all()
        assert len(commits) == 2
        for commit in commits:
            assert commit.organization_id == other_org.id

    def test_push_event_create_commits_and_authors(self):
        repo = self.create_repo('getsentry/sentry')
        response = self.client.post(
            self.url,
            data=PUSH_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        assert response.status_code == 204

        commits = Commit.objects.all()
        assert len(commits) == 2
        for commit in commits:
            assert commit.key
            assert commit.message
            assert commit.author
            assert commit.date_added
            assert commit.repository_id == repo.id
            assert commit.organization_id == self.organization.id

        authors = CommitAuthor.objects.all()
        assert len(authors) == 2
        for author in authors:
            assert author.email
            assert 'example.org' in author.email
            assert author.name
            assert author.organization_id == self.organization.id

    def test_push_event_ignore_commit(self):
        self.create_repo('getsentry/sentry')
        response = self.client.post(
            self.url,
            data=PUSH_EVENT_IGNORED_COMMIT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        assert response.status_code == 204
        assert 0 == Commit.objects.count()

    def test_push_event_known_author(self):
        CommitAuthor.objects.create(
            organization_id=self.organization.id,
            email='jordi@example.org',
            name='Jordi'
        )
        self.create_repo('getsentry/sentry')
        response = self.client.post(
            self.url,
            data=PUSH_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Push Hook'
        )
        assert response.status_code == 204
        assert 2 == CommitAuthor.objects.count(), 'No dupes made'

    @pytest.mark.incomplete
    def test_push_event_create_commits_more_than_20(self):
        pass

    def test_merge_event_missing_repo(self):
        response = self.client.post(
            self.url,
            data=MERGE_REQUEST_OPENED_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Merge Request Hook'
        )
        assert response.status_code == 204
        assert 0 == PullRequest.objects.count()

    def test_merge_event_create_pull_request(self):
        self.create_repo('getsentry/sentry')
        response = self.client.post(
            self.url,
            data=MERGE_REQUEST_OPENED_EVENT,
            content_type='application/json',
            HTTP_X_GITLAB_TOKEN=WEBHOOK_TOKEN,
            HTTP_X_GITLAB_EVENT='Merge Request Hook'
        )
        assert response.status_code == 204
        author = CommitAuthor.objects.all().first()
        assert author.email
        assert author.name
        assert author.organization_id == self.organization.id

        pull = PullRequest.objects.all().first()
        assert pull.title
        assert pull.message
        assert pull.date_added
        assert pull.author == author
        assert pull.merge_commit_sha is None
        assert pull.organization_id == self.organization.id
