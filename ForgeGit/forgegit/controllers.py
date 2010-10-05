from tg import expose, url, override_template, redirect
from tg.decorators import with_trailing_slash, without_trailing_slash
from pylons import c

from allura.controllers import repository
from allura.lib.security import require, has_artifact_access
from allura.lib import patience

from .widgets import GitRevisionWidget, GitLog

revision_widget = GitRevisionWidget()
log_widget = GitLog()

def on_import():
    BranchBrowser.CommitBrowserClass = CommitBrowser

class BranchBrowser(repository.BranchBrowser):

    def _check_security(self):
        require(has_artifact_access('read', c.app.repo))

    @expose('jinja:git/index.html')
    @with_trailing_slash
    def index(self, limit=None, page=0, count=0, **kw):
        latest = c.app.repo.latest(branch=self._branch)
        if not latest:
            return dict(allow_fork=False, log=[])
        redirect(latest.url() + 'tree')

    @expose('jinja:git/log.html')
    @with_trailing_slash
    def log(self, limit=None, page=0, count=0, **kw):
        c.log_widget=log_widget
        return super(BranchBrowser, self).index(limit, page, count)

    @expose()
    def _lookup(self, rev, *remainder):
        return CommitBrowser(rev), remainder

class CommitBrowser(repository.CommitBrowser):
    revision_widget = GitRevisionWidget()

    @expose('jinja:git/commit.html')
    @with_trailing_slash
    def index(self, **kw):
        return super(CommitBrowser, self).index()

on_import()
