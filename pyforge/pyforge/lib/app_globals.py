# -*- coding: utf-8 -*-

"""The application's Globals object"""

__all__ = ['Globals']
import logging
import socket
from urllib import urlencode

import pkg_resources

from tg import config, session
from pylons import c, request
import paste.deploy.converters
import pysolr
import markdown
from carrot.connection import BrokerConnection
from carrot.messaging import Publisher
from pymongo.bson import ObjectId

from pyforge import model as M
from pyforge.lib.markdown_extensions import ForgeExtension

log = logging.getLogger(__name__)

class Globals(object):
    """Container for objects available throughout the life of the application.

    One instance of Globals is created during application initialization and
    is available during requests via the 'app_globals' variable.

    """

    def __init__(self):
        """Do nothing, by default."""
        self.pyforge_templates = pkg_resources.resource_filename('pyforge', 'templates')
        self.solr_server = config.get('solr.server')
        if self.solr_server:
            self.solr =  pysolr.Solr(self.solr_server)
        else: # pragma no cover
            self.solr = None
        self.use_queue = paste.deploy.converters.asbool(
            config.get('use_queue', False))
        self.conn = BrokerConnection(
            hostname=config.get('amqp.hostname', 'localhost'),
            port=config.get('amqp.port', 5672),
            userid=config.get('amqp.userid', 'testuser'),
            password=config.get('amqp.password', 'testpw'),
            virtual_host=config.get('amqp.vhost', 'testvhost'))
        self.publisher = dict(
            audit=Publisher(connection=self.conn, exchange='audit', auto_declare=False),
            react=Publisher(connection=self.conn, exchange='react', auto_declare=False))
        self.markdown = markdown.Markdown(
            extensions=['codehilite', ForgeExtension(),'meta'],
            output_format='html4')

        self.oid_store = M.OpenIdStore()

    def oid_session(self):
        if 'openid_info' in session:
            return session['openid_info']
        else:
            session['openid_info'] = result = {}
            session.save()
            return result
        
    def app_static(self, resource, app=None):
        app = app or c.app
        return ''.join(
            [ config['static_root'],
              app.config.plugin_name,
              '/',
              resource ])

    def set_project(self, pid):
        c.project = M.Project.query.get(shortname=pid)

    def set_app(self, name):
        c.app = c.project.app_instance(name)

    def publish(self, xn, key, message=None, **kw):
        project = getattr(c, 'project', None)
        app = getattr(c, 'app', None)
        user = getattr(c, 'user', None)
        if message is None: message = {}
        if project:
            message.setdefault('project_id', project._id)
        if app:
            message.setdefault('mount_point', app.config.options.mount_point)
        if user:
            if user._id is None:
                message.setdefault('user_id',  None)
            else:
                message.setdefault('user_id',  user._id)
        # Make message safe for serialization
        if kw.get('serializer', 'json') in ('json', 'yaml'):
            for k, v in message.items():
                if isinstance(v, ObjectId):
                    message[k] = str(v)
        if hasattr(c, 'queued_messages'):
            c.queued_messages.append(dict(
                    xn=xn,
                    message=message,
                    routing_key=key,
                    **kw))
        else:
            self._publish(xn, message, routing_key=key, **kw)

    def _publish(self, xn, message, routing_key, **kw):
        try:
            self.publisher[xn].send(message, routing_key=routing_key, **kw)
        except socket.error: # pragma no cover
            return
            log.exception('''Failure publishing message:
xn         : %r
routing_key: %r
data       : %r
''', xn, routing_key, message)

    def url(self, base, **kw):
        params = urlencode(kw)
        if params:
            return '%s://%s%s?%s' % (request.scheme, request.host, base, params)
        else:
            return '%s://%s%s' % (request.scheme, request.host, base)
