import sys
import time
from collections import defaultdict

import tg
import pymongo
from pylons import c
from paste.deploy.converters import asint

from ming.orm import MappedClass, mapper, ThreadLocalORMSession, session, state

from . import base

class ShowModelsCommand(base.Command):
    min_args=1
    max_args=1
    usage = 'NAME <ini file>'
    summary = 'Show the inheritance graph of all Ming models'
    parser = base.Command.standard_parser(verbose=True)

    def command(self):
        self.basic_setup()
        graph = build_model_inheritance_graph()
        for depth, cls in dfs(MappedClass, graph):
            for line in dump_cls(depth, cls):
                print line

class ReindexCommand(base.Command):
    min_args=0
    max_args=1
    usage = 'NAME <ini file>'
    summary = 'Reindex and re-shortlink all artifacts'
    parser = base.Command.standard_parser(verbose=True)
    parser.add_option('-p', '--project', dest='project',  default=None,
                      help='project to reindex')

    def command(self):
        from allura import model as M
        self.basic_setup()
        graph = build_model_inheritance_graph()
        # Clear shortlinks
        if self.options.project is None:
            projects = M.Project.query.find()
        else:
            projects = [ M.Project.query.get(shortname=self.options.project) ]
        for p in projects:
            base.log.info('Reindex project %s', p.shortname)
            c.project = p
            M.ArtifactLink.query.remove({})
            for _, acls in dfs(M.Artifact, graph):
                base.log.info('  %s', acls)
                for a in acls.query.find():
                    state(a).soil()
                session(acls).flush()
                session(acls).clear()

class EnsureIndexCommand(base.Command):
    min_args=0
    max_args=1
    usage = 'NAME [<ini file>]'
    summary = 'Run ensure_index on all mongo objects'
    parser = base.Command.standard_parser(verbose=True)

    def command(self):
        from allura import model as M
        self.basic_setup()
        # Collect indexes by collection name
        main_indexes = defaultdict(lambda: ([], []))
        project_indexes = defaultdict(lambda: ([], []))
        base.log.info('Collecting indexes...')
        for name, cls in MappedClass._registry.iteritems():
            cname = cls.__mongometa__.name
            if cname is None:
                base.log.info('... skipping abstract class %s', cls)
                continue
            base.log.info('... for class %s', cls)
            indexes = getattr(cls.__mongometa__, 'indexes', []) or []
            uindexes = getattr(cls.__mongometa__, 'unique_indexes', []) or []
            if cls.__mongometa__.session in (
                M.main_orm_session, M.repository_orm_session):
                idx = main_indexes[cname]
            else:
                idx = project_indexes[cname]
            idx[0].extend(indexes)
            idx[1].extend(uindexes)
        base.log.info('Updating indexes for main DB')
        db = M.main_doc_session.db
        for name, (indexes, uindexes) in main_indexes.iteritems():
            self._update_indexes(db[name], indexes, uindexes)
        base.log.info('Updating indexes for project DBs')
        projects = M.Project.query.find().all()
        configured_dbs = set()
        for p in projects:
            db = p.database_uri
            if db in configured_dbs: continue
            configured_dbs.add(db)
            c.project = p
            db = M.project_doc_session.db
            base.log.info('... DB: %s', db)
            for name, (indexes, uindexes) in project_indexes.iteritems():
                self._update_indexes(db[name], indexes, uindexes)

    def _update_indexes(self, collection, indexes, uindexes):
        indexes = set(map(tuple, indexes))
        uindexes = set(map(tuple, uindexes))
        prev_indexes = {}
        prev_uindexes = {}
        for iname, fields in collection.index_information().iteritems():
            if iname == '_id_': continue
            if fields.get('unique'):
                prev_uindexes[iname] = tuple(fields['key'])
            else:
                prev_indexes[iname] = tuple(fields['key'])
        # Drop obsolete indexes
        for iname, key in prev_indexes.iteritems():
            if key not in indexes:
                base.log.info('...... drop index %s:%s', collection.name, iname)
                collection.drop_index(iname)
        for iname, key in prev_uindexes.iteritems():
            if key not in uindexes:
                base.log.info('...... drop index %s:%s', collection.name, iname)
                collection.drop_index(iname)
        # Ensure all indexes
        for idx in map(list, indexes):
            base.log.info('...... ensure index %s:%s', collection.name, idx)
            collection.ensure_index(idx, background=True)
        for idx in map(list, uindexes):
            base.log.info('...... ensure unique index %s:%s', collection.name, idx)
            collection.ensure_index(idx, background=True, unique=True)

def build_model_inheritance_graph():
    graph = dict((c, ([], [])) for c in MappedClass._registry.itervalues())
    for cls, (parents, children)  in graph.iteritems():
        for b in cls.__bases__:
            if b not in graph: continue
            parents.append(b)
            graph[b][1].append(cls)
    return graph

def dump_cls(depth, cls):
    indent = ' '*4*depth
    yield indent + '%s.%s' % (cls.__module__, cls.__name__)
    m = mapper(cls)
    for p in m.properties:
        s = indent*2 + ' - ' + str(p)
        if hasattr(p, 'field_type'):
            s += ' (%s)' % p.field_type
        yield s

def dump(root, graph):
    for depth, cls in dfs(MappedClass, graph):
        indent = ' '*4*depth

def dfs(root, graph, depth=0):
    yield depth, root
    for c in graph[root][1]:
        for r in dfs(c, graph, depth+1):
            yield r


def pm(etype, value, tb): # pragma no cover
    import pdb, traceback
    try:
        from IPython.ipapi import make_session; make_session()
        from IPython.Debugger import Pdb
        sys.stderr.write('Entering post-mortem IPDB shell\n')
        p = Pdb(color_scheme='Linux')
        p.reset()
        p.setup(None, tb)
        p.print_stack_trace()
        sys.stderr.write('%s: %s\n' % ( etype, value))
        p.cmdloop()
        p.forget()
        # p.interaction(None, tb)
    except ImportError:
        sys.stderr.write('Entering post-mortem PDB shell\n')
        traceback.print_exception(etype, value, tb)
        pdb.post_mortem(tb)

