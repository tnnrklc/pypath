#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  This file is part of the `pypath` python module
#  Provides classes for each database for annotations of proteins and complexes.
#  Also provides meta-annotations for the databases.
#
#  Copyright
#  2014-2020
#  EMBL, EMBL-EBI, Uniklinik RWTH Aachen, Heidelberg University
#
#  File author(s): Dénes Türei (turei.denes@gmail.com)
#                  Nicolàs Palacio
#                  Olga Ivanova
#
#  Distributed under the GPLv3 License.
#  See accompanying file LICENSE.txt or copy at
#      http://www.gnu.org/licenses/gpl-3.0.html
#
#  Website: http://pypath.omnipathdb.org/
#

from future.utils import iteritems
from past.builtins import xrange, range, reduce

import os
import sys
import importlib as imp
import collections
import itertools
import traceback

try:
    import cPickle as pickle
except:
    import pickle

import numpy as np
import pandas as pd

import pypath.inputs.main as dataio
import pypath.inputs.cellphonedb as cellphonedb
import pypath.inputs.lrdb as lrdb
import pypath.share.common as common
import pypath.share.settings as settings
import pypath.utils.mapping as mapping
import pypath.utils.reflists as reflists
import pypath.utils.uniprot as utils_uniprot
import pypath.internals.resource as resource
import pypath.utils.go as go
import pypath.core.intercell_annot as intercell_annot
import pypath.share.session as session_mod
import pypath.internals.annot_formats as annot_formats
import pypath.core.complex as complex
import pypath.internals.intera as intera
import pypath.core.entity as entity

#TODO this should be part of json files
protein_sources_default = {
    'Dgidb',
    'Membranome',
    'Exocarta',
    'Vesiclepedia',
    'Matrisome',
    'Surfaceome',
    'CellSurfaceProteinAtlas',
    'CellSurfaceProteinAtlasCellType',
    'HumanPlasmaMembraneReceptome',
    'Matrixdb',
    'Locate',
    'GOIntercell',
    'CellPhoneDB',
    'Ramilowski2015',
    'Ramilowski2015Location',
    'Kirouac2010',
    'GuideToPharmacology',
    'Adhesome',
    'Integrins',
    'Opm',
    'Topdb',
    'Hgnc',
    'Zhong2015',
    'HumanProteinAtlas',
    'HumanProteinAtlasSubcellular',
    'HumanProteinAtlasSecretome',
    'Comppi',
    'SignorPathways',
    'SignalinkPathways',
    'SignalinkFunctions',
    'KeggPathways',
    'NetpathPathways',
    'Cpad',
    'Disgenet',
    'Kinasedotcom',
    'Phosphatome',
    'Tfcensus',
    'Intogen',
    'CancerGeneCensus',
    'Cancersea',
    'Msigdb',
    'Lrdb',
    'Baccin2019',
    'Almen2009',
    'Phobius',
    'Icellnet',
    'Cellcellinteractions',
    'Italk',
    'Embrace',
    'UniprotLocation',
    'UniprotFamily',
    'UniprotTopology',
    'UniprotTissue',
    'Tcdb',
    'Mcam',
    'Gpcrdb',
}

#TODO this should be part of json files
complex_sources_default = {
    'CellPhoneDBComplex',
    'CorumFuncat',
    'CorumGO',
    'HpmrComplex',
    'IcellnetComplex',
}

#TODO this should be part of json files
default_fields = {
    'Matrisome': ('mainclass', 'subclass'),
    'Locate': ('location',),
    'Vesiclepedia': ('vesicle',),
    'Exocarta': ('vesicle',),
    'Ramilowski_location': ('location',),
    'HPA': ('tissue', 'level'),
    'CellPhoneDB': (
        'receptor',
        'adhesion',
        'cytoplasm',
        'peripheral',
        'secretion',
        'secreted',
        'transporter',
        'transmembrane',
        'extracellular',
    ),
    'CellPhoneDB_Complex': (
        'receptor',
        'adhesion',
        'cytoplasm',
        'peripheral',
        'secretion',
        'secreted',
        'transporter',
        'transmembrane',
        'extracellular',
    ),
    'Cpad': (
        'cancer',
        'effect_on_cancer',
    ),
    'Disgenet': (
        'disease',
    ),
}


class CustomAnnotation(session_mod.Logger):


    def __init__(
            self,
            class_definitions = None,
            pickle_file = None,
            annotdb_pickle_file = None,
        ):

        if not hasattr(self, '_log_name'):

            session_mod.Logger.__init__(self, name = 'annot')

        self.pickle_file = pickle_file
        self.annotdb_pickle_file = annotdb_pickle_file
        self._class_definitions_provided = class_definitions
        self.network = None

        self.load()


    def reload(self):
        """
        Reloads the object from the module level.
        """

        modname = self.__class__.__module__
        mod = __import__(modname, fromlist = [modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)


    def load(self):

        if self.pickle_file and os.path.exists(self.pickle_file):

            self.load_from_pickle(pickle_file = self.pickle_file)

        else:

            self.pre_build()
            self.build()

        self.post_load()


    def pre_build(self):

        pass


    def build(self):

        self.ensure_annotdb()

        self._class_definitions = {}
        self.add_class_definitions(self._class_definitions_provided or {})

        self.classes = {}
        self.populate_classes()


    def post_load(self):

        pass


    def ensure_annotdb(self):

        self.annotdb = get_db(pickle_file = self.annotdb_pickle_file)


    def add_class_definitions(self, class_definitions):

        if not isinstance(class_definitions, dict):

            class_definitions = dict(
                (
                    classdef.key,
                    classdef
                ) for classdef in class_definitions
            )

        self._class_definitions.update(class_definitions)


    def populate_classes(self, update = False):
        """
        Creates a classification of proteins according to their roles
        in the intercellular communication.
        """

        if self.pickle_file:

            self.load_from_pickle(pickle_file = self.pickle_file)
            return

        for classdef in self._class_definitions.values():

            if classdef.name not in self.classes or update:

                self.create_class(classdef)


    def load_from_pickle(self, pickle_file):

        self._log('Loading from pickle `%s`.' % pickle_file)

        with open(pickle_file, 'rb') as fp:

            self.classes = pickle.load(fp)

        self._update_complex_attribute_classes()

        self._log('Loaded from pickle `%s`.' % pickle_file)


    def save_to_pickle(self, pickle_file):

        self._log('Saving to pickle `%s`.' % pickle_file)

        self._update_complex_attribute_classes()

        with open(pickle_file, 'wb') as fp:

            pickle.dump(
                obj = self.classes,
                file = fp,
            )

        self._log('Saved to pickle `%s`.' % pickle_file)


    def _update_complex_attribute_classes(self):

        complex.ComplexAggregator._update_complex_attribute_classes_static(
            self.classes.keys(),
            mod = sys.modules[__name__],
        )


    def create_class(self, classdef):
        """
        Creates a category of entities by processing a custom definition.
        """

        self.classes[classdef.key] = self.process_annot(classdef)


    def process_annot(self, classdef):
        """
        Processes an annotation definition and returns a set of identifiers.
        """

        class_set = set()

        if isinstance(classdef.resource, set):

            class_set = classdef.resource

        elif isinstance(classdef.resource, common.basestring):

            if classdef.resource in self.annotdb.annots:

                if not classdef.args:

                    class_set = (
                        self.annotdb.annots[classdef.resource].to_set()
                    )

                else:

                    class_set = (
                        self.annotdb.annots[classdef.resource].get_subset(
                            **classdef.args
                        )
                    )

        elif callable(classdef.resource):

            class_set = classdef.resource(**(classdef.args or {}))

        elif isinstance(classdef.resource, annot_formats.AnnotOp):

            class_set = self._execute_operation(classdef.resource)

        if classdef.exclude:

            class_set = class_set - classdef.exclude

        transmitter, receiver = self._get_transmitter_receiver(classdef)

        return annot_formats.AnnotationGroup(
            members = class_set,
            name = classdef.name,
            parent = classdef.parent,
            aspect = classdef.aspect,
            resource = classdef.resource_str, # the actual database name
            scope = classdef.scope,
            source = classdef.source, # resource_specific / composite
            transmitter = transmitter,
            receiver = receiver,
        )


    def _execute_operation(self, annotop):
        """
        Executes a set operation on anntation sets.
        """

        if (
            isinstance(annotop.annots, common.basestring) and
            annotop.annots.startswith('~')
        ):

            annots = self._collect_by_parent(annotop.annots)

        else:

            annots = tuple(
                (
                    self._execute_operation(_annot)
                        if isinstance(_annot, annot_formats.AnnotOp) else
                    self.process_annot(_annot)
                        if isinstance(_annot, annot_formats.AnnotDef) else
                    _annot
                        if isinstance(_annot, set) else
                    self.select(_annot)
                )
                for _annot in annotop.annots
            )

        return annotop.op(*annots)


    def _collect_by_parent(self, parent):

        parent = parent.strip('~')
        resource = None
        parent_resource = parent.split('~')

        if len(parent_resource) == 2:

            parent, resource = parent_resource

        return tuple(
            self.select(classdef.key())
            for classdef in self._class_definitions.values()
            if (
                classdef.parent == parent and
                (
                    not resource or
                    classdef.resource_str == resource
                )
            )
        )


    def _get_transmitter_receiver(self, classdef):

        transmitter = classdef.transmitter
        receiver = classdef.receiver

        if transmitter is None or receiver is None:

            composite_resource_name = settings.get(
                'annot_composite_database_name'
            )

            name, parent, resource = classdef.key

            for key, parentdef in self._class_definitions.keys():

                if (
                    parentdef.name == parent and
                    parentdef.parent == parent and
                    (
                        parantdef.source == 'composite' or
                        parentdef.resource == composite_resource_name
                    )
                ):

                    transmitter = (
                        transmitter
                            if transmitter is not None else
                        parent.transmitter
                    )
                    receiver = (
                        receiver
                            if receiver is not None else
                        parent.receiver
                    )
                    break

        return transmitter, receiver


    def select(
            self,
            name,
            parent = None,
            resource = None,
            entity_types = None,
        ):
        """
        Retrieves a class by its name and loads it if hasn't been loaded yet
        but the name present in the class definitions.
        """

        key = name if isinstance(name, tuple) else (name, parent, resource)

        if key not in self.classes and key in self._class_definitions:

            self.create_class(self._class_definitions[key])

        if key in self.classes:

            return entity.Entity.filter_entity_type(
                self.classes[name],
                entity_type = entity_types,
            )

        self._log(
            'No such annotation class: `name=%s, '
            'parent=%s, resource=%s`' % key
        )


    # synonym for old name
    get_class = select


    def labels(
            self,
            name,
            parent = None,
            resource = None,
            entity_type = None,
        ):
        """
        Same as ``select`` but returns a list of labels (more human readable).
        """

        return mapping.label(
            self.select(
                name = name,
                parent = parent,
                resource = resource,
                entity_type = entity_type,
            )
        )


    def show(
            self,
            name,
            parent = None,
            resource = None,
            **kwargs
        ):
        """
        Same as ``select`` but prints a table to the console with basic
        information from the UniProt datasheets.
        """

        table_param = table_param or {}

        utils_uniprot.info(
            *self.select(
                name = name,
                parent = parent,
                resource = resource,
                entity_type = 'protein',
            ),
            **kwargs
        )


    def _key(self, name, parent = None, resource = None):

        return name if isinstance(name, tuple) else (name, parent, resource)


    def get_class_scope(self, name, parent = None, resource = None):

        key = self._key(name, parent, resource)

        return self.classes[key].scope


    def get_resource(self, name, parent = None, resource = None):

        key = self._key(name, parent, resource)

        return self.classes[key].resource


    def get_aspect(self, name, parent = None, resource = None):

        key = self._key(name, parent, resource)

        return self.classes[key].aspect


    def get_source(self, name, parent = None, resource = None):

        key = self._key(name, parent, resource)

        return self.classes[key].source


    def get_parent(self, name, parent = None, resource = None):

        key = self._key(name, parent, resource)

        return self.classes[key].parent


    def get_class_label(self, name, parent = None, resource = None):

        cls = self.select(name, parent = parent, resource = resource)

        return cls.label


    def __len__(self):

        return len(self.classes)


    def __contains__(self, other):

        return (
            other in self.classes or
            any(other in v for v in self.classes.values)
        )


    def make_df(self, all_annotations = False, full_name = False):
        """
        Creates a ``pandas.DataFrame`` where each record assigns a
        molecular entity to an annotation category. The data frame will
        be assigned to the ``df`` attribute.
        """

        self._log('Creating data frame from custom annotation.')

        header = [
            'category',
            'parent',
            'database',
            'scope',
            'aspect',
            'source',
            'uniprot',
            'genesymbol',
            'entity_type',
        ]

        dtypes = {
            'category':    'category',
            'parent':      'category',
            'database':    'category',
            'scope':       'category',
            'aspect':      'category',
            'source':      'category',
            'uniprot':     'category',
            'genesymbol':  'category',
            'entity_type': 'category',
        }

        if full_name:

            header.insert(-1, 'full_name')
            dtypes['full_name'] = 'category'

        # this won't be needed any more I guess
        #self.collect_classes()

        self.df = pd.DataFrame(
            [
                # annotation category, entity id
                [
                    cls,
                    cls.parent,
                    cls.resource,
                    cls.scope,
                    cls.aspect,
                    cls.source,
                    uniprot.__str__(),
                    (
                        mapping.map_name0(uniprot, 'uniprot', 'genesymbol')
                            if isinstance(uniprot, common.basestring) else
                        'COMPLEX:%s' % uniprot.genesymbol_str
                            if hasattr(uniprot, 'genesymbol_str') else
                        uniprot.__str__()
                    ),
                ] +
                # full name
                (
                    [
                        '; '.join(
                            mapping.map_name(
                                uniprot,
                                'uniprot',
                                'protein-name',
                            )
                        ),
                    ]
                    if full_name else []
                ) +
                # entity type
                [
                    'complex'
                        if hasattr(uniprot, 'genesymbol_str') else
                    'mirna'
                        if uniprot.startswith('MIMAT') else
                    'protein'
                ] +
                # all annotations
                (
                    [self.annotdb.all_annotations_str(uniprot)]
                        if all_annotations else
                    []
                )
                for cls, members in iteritems(self.classes)
                for uniprot in members
            ],
            columns = header + (
                ['all_annotations'] if all_annotations else []
            ),
        ).astype(dtypes)

        self._log(
            'Custom annotation data frame has been created. '
            'Memory usage: %s.' % common.df_memory_usage(self.df)
        )


    def counts(
            self,
            name = None,
            parent = None,
            resource = None,
            scope = None,
            aspect = None,
            source = None,
            transmitter = None,
            receiver = None,
            entity_type = 'protein',
            labels = True,
        ):
        """
        Returns a dict with number of elements in each class.

        :param bool labels:
            Use keys or labels as keys in the returned dict.

        All other arguments passed to ``iter_classes``.
        """

        return dict(
            (
                cls.label if labels else cls.key,
                len(cls)
            )
            for cls in self.iter_classes(
                parent = parent,
                resource = resource,
                scope = scope,
                aspect = aspect,
                source = source,
                transmitter = transmitter,
                receiver = receiver,
                entity_type = entity_type,
            )
            if len(cls) > 0
        )

    # synonym
    count_by_class = counts


    def iter_classes(
            self,
            name = None,
            parent = None,
            resource = None,
            scope = None,
            aspect = None,
            source = None,
            transmitter = None,
            receiver = None,
            entity_type = None,
        ):

        return filter_classes(
            classes = self.classes.values(),
            name = name,
            parent = parent,
            resource = resource,
            scope = scope,
            aspect = aspect,
            source = source,
            transmitter = transmitter,
            receiver = receiver,
            entity_type = entity_type,
        )


    def filter_classes(
            self,
            classes,
            name = None,
            parent = None,
            resource = None,
            scope = None,
            aspect = None,
            source = None,
            transmitter = None,
            receiver = None,
            entity_type = None,
        ):

        name = common.to_set(name)
        parent = common.to_set(parent)
        resource = common.to_set(resource)
        scope = common.to_set(scope)
        aspect = common.to_set(aspect)
        source = common.to_set(source)

        for cls in classes:

            if (
                (not name or cls.name in name) and
                (not parent or cls.parent in parent) and
                (not resource or cls.resource in resource) and
                (not scope or cls.scope in scope) and
                (not aspect or cls.aspect in aspect) and
                (not source or cls.source in source) and
                (transmitter is None or cls.transmitter == transmitter) and
                (receiver is None or cls.receiver == receiver)
            ):

                yield self.filter_entity_type(cls, entity_type = entity_type)


    def filter_entity_type(self, cls):

        return cls.filter_entity_type(entity_type = entity_type)


    def network_df(
            self,
            network = None,
            resources = None,
            classes = None,
            source_classes = None,
            target_classes = None,
            only_directed = False,
            only_undirected = False,
            only_effect = None,
            only_proteins = False,
            only_class_levels = None,
        ):
        """
        Combines the annotation data frame and a network data frame.
        Creates a ``pandas.DataFrame`` where each record is an interaction
        between a pair of molecular enitities labeled by their annotations.

        network : pypath.network.Network,pandas.DataFrame
            A ``pypath.network.Network`` object or a data frame with network
            data.
        resources : set,None
            Use only these network resources.
        classes : set,None
            Use only these annotation classes.
        only_directed : bool
            Use only the directed interactions.
        only_undirected : bool
            Use only the undirected interactions. Specifically for retrieving
            and counting the interactions without direction information.
        only_effect : int,None
            Use only the interactions with this effect. Either -1 or 1.
        only_proteins : bool
            Use only the interactions where each of the partners is a protein
            (i.e. not complex, miRNA, small molecule or other kind of entity).
        """

        if hasattr(self, 'interclass_network'):

            return self.filter_interclass_network(
                network = self.interclass_network,
                resources = resources,
                classes = classes,
                source_classes = source_classes,
                target_classes = target_classes,
                only_directed = only_directed,
                only_undirected = only_undirected,
                only_effect = only_effect,
                only_proteins = only_proteins,
                only_class_levels = only_class_levels,
            )

        self._log('Combining custom annotation with network data frame.')

        network_df = (
            self._network_df(network)
                if network is not None else
            self.network
        )

        if network_df is None:

            self._log('No network provided, no default network set.')

            return

        annot_df = self.df

        if only_class_levels:

            only_class_levels = common.to_set(only_class_levels)
            annot_df = annot_df[annot_df.class_type.isin(only_class_levels)]

        if (
            not only_directed and
            not only_effect and
            not classes and (
                source_classes or
                target_classes
            )
        ):

            classes = set.union(
                common.to_set(source_classes),
                common.to_set(target_classes),
            )

        if classes:

            annot_df = self._filter_by_classes(annot_df, classes)

        if resources:

            filter_op = (
                network_df.sources.eq
                    if isinstance(resources, common.basestring) else
                network_df.sources.isin
            )

            network_df = network_df[filter_op(resources)]

        if only_directed:

            network_df = network_df[network_df.directed]

        if only_undirected:

            network_df = network_df[np.logical_not(network_df.directed)]

        if only_effect:

            network_df = network_df[network_df.effect == only_effect]

        if only_proteins:

            network_df = network_df[
                (network_df.type_a == 'protein') &
                (network_df.type_b == 'protein')
            ]

        annot_network_df = pd.merge(
            network_df,
            self._filter_by_classes(annot_df, source_classes),
            suffixes = ['', '_a'],
            how = 'inner',
            left_on = 'id_a',
            right_on = 'uniprot',
        )

        # if we deal with undirected interactions but source & target classes
        if (
            not only_directed and
            not only_effect and (
                source_classes or
                target_classes
            )
        ):

            annot_network_df = pd.concat(
                (

                    annot_network_df,

                    pd.merge(
                        network_df[
                            np.logical_not(network_df.directed)
                        ][
                            network_df.columns[
                                np.r_[1, 0, 3, 2, 4:len(network_df.columns)]
                            ]
                        ][
                            ['id_a', 'id_b', 'type_a', 'type_b'] +
                            list(network_df.columns)[4:]
                        ],
                        self._filter_by_classes(annot_df, source_classes),
                        suffixes = ['', '_a'],
                        how = 'inner',
                        left_on = 'id_a',
                        right_on = 'uniprot',
                    ),

                ),

                sort = False,
                ignore_index = True,
            )

        annot_network_df.id_a = annot_network_df.id_a.astype('category')

        annot_network_df = pd.merge(
            annot_network_df,
            self._filter_by_classes(annot_df, target_classes),
            suffixes = ['_a', '_b'],
            how = 'inner',
            left_on = 'id_b',
            right_on = 'uniprot',
        )

        annot_network_df.id_b = annot_network_df.id_b.astype('category')

        #annot_network_df.set_index(
            #'id_a',
            #drop = False,
            #inplace = True,
        #)

        self._log(
            'Combined custom annotation data frame with network data frame. '
            'Memory usage: %s.' % common.df_memory_usage(annot_network_df)
        )

        return annot_network_df


    def set_interclass_network_df(self, **kwargs):
        """
        Creates a data frame of the whole inter-class network and keeps it
        assigned to the instance in order to make subsequent queries faster.
        """

        self.unset_interclass_network_df()

        self.interclass_network = self.get_interclass_network_df(**kwargs)


    def get_interclass_network_df(self, **kwargs):
        """
        If the an interclass network is already present the ``network``
        and other ``kwargs`` provided not considered. Otherwise these
        are passed to ``network_df``.
        """

        return (
            self.interclass_network
                if hasattr(self, 'interclass_network') else
            self.network_df(**kwargs)
        )


    def unset_interclass_network_df(self):

        if hasattr(self, 'interclass_network'):

            del self.interclass_network


    @classmethod
    def filter_interclass_network(
            cls,
            network,
            resources = None,
            classes = None,
            source_classes = None,
            target_classes = None,
            only_directed = False,
            only_undirected = False,
            only_effect = None,
            only_proteins = False,
            only_class_levels = None,
        ):

        filter_idx = np.full(network.shape[0], True)

        if only_class_levels:

            only_class_levels = common.to_set(only_class_levels)
            filter_idx = np.logical_and(
                filter_idx,
                np.logical_and(
                    network.class_type_a.isin(only_class_levels),
                    network.class_type_b.isin(only_class_levels)
                )
            )

        if (
            not only_directed and
            not only_effect and
            not classes and (
                source_classes or
                target_classes
            )
        ):

            classes = set.union(
                common.to_set(source_classes),
                common.to_set(target_classes),
            )

        if classes:

            op = 'eq' if isinstance(classes, common.basestring) else 'isin'

            filter_idx = np.logical_and(
                filter_idx,
                np.logical_or(
                    getattr(network.category_a, op)(classes),
                    getattr(network.category_b, op)(classes),
                )
            )

        if source_classes:

            op = (
                'eq'
                    if isinstance(source_classes, common.basestring) else
                'isin'
            )
            filter_idx = np.logical_and(
                filter_idx,
                np.logical_or(
                    getattr(network.category_a, op)(source_classes),
                    np.logical_and(
                        np.logical_not(network.directed),
                        getattr(network.category_b, op)(source_classes)
                    )
                )
            )

        if target_classes:

            op = (
                'eq'
                    if isinstance(target_classes, common.basestring) else
                'isin'
            )
            filter_idx = np.logical_and(
                filter_idx,
                np.logical_or(
                    getattr(network.category_b, op)(target_classes),
                    np.logical_and(
                        np.logical_not(network.directed),
                        getattr(network.category_a, op)(target_classes)
                    )
                )
            )

        if resources:

            filter_op = (
                network.sources.eq
                    if isinstance(resources, common.basestring) else
                network.sources.isin
            )

            filter_idx = np.logical_and(
                filter_idx,
                filter_op(resources)
            )

        if only_directed:

            filter_idx = np.logical_and(filter_idx, network.directed)

        if only_undirected:

            filter_idx = np.logical_and(
                filter_idx,
                np.logical_not(network.directed)
            )

        if only_effect:

            filter_idx = np.logical_and(
                filter_idx,
                network.effect == only_effect
            )

        if only_proteins:

            filter_idx = np.logical_and(
                filter_idx,
                np.logical_and(
                    network.type_a == 'protein',
                    network.type_b == 'protein'
                )
            )

        network = network[filter_idx]

        return network


    #
    # Below only thin wrappers to make the interface more intuitive
    # without knowing the argument names
    #

    #
    # Building a network of connections between classes
    #

    def inter_class_network(
            self,
            source_classes = None,
            target_classes = None,
            network = None,
            **kwargs
            ):

        return self.network_df(
            network = network,
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        )


    def inter_class_network_undirected(
            self,
            source_classes = None,
            target_classes = None,
            network = None,
            **kwargs
        ):

        kwargs.update({'only_undirected': True})

        return self.network_df(
            network = network,
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        )


    def inter_class_network_directed(
            self,
            source_classes = None,
            target_classes = None,
            network = None,
            **kwargs
        ):

        kwargs.update({'only_directed': True})

        return self.network_df(
            network = network,
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        )


    def inter_class_network_stimulatory(
            self,
            source_classes = None,
            target_classes = None,
            network = None,
            **kwargs
        ):

        kwargs.update({
            'only_directed': True,
            'only_effect': 1,
        })

        return self.network_df(
            network = network,
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        )


    def inter_class_network_inhibitory(
            self,
            source_classes = None,
            target_classes = None,
            network = None,
            **kwargs
        ):

        kwargs.update({
            'only_directed': True,
            'only_effect': -1,
        })

        return self.network_df(
            network = network,
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        )

    #
    # Counting connections between classes (total)
    #

    def count_inter_class_connections(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        return self.inter_class_network(
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        ).groupby(['id_a', 'id_b']).ngroups


    # synonym
    count_inter_class_connections_all = count_inter_class_connections


    def count_inter_class_connections_undirected(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        return self.inter_class_network_undirected(
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        ).groupby(['id_a', 'id_b']).ngroups


    def count_inter_class_connections_directed(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        return self.inter_class_network_directed(
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        ).groupby(['id_a', 'id_b']).ngroups


    def count_inter_class_connections_stimulatory(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        return self.inter_class_network_stimulatory(
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        ).groupby(['id_a', 'id_b']).ngroups


    def count_inter_class_connections_inhibitory(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        return self.inter_class_network_inhibitory(
            source_classes = source_classes,
            target_classes = target_classes,
            **kwargs
        ).groupby(['id_a', 'id_b']).ngroups


    #
    # Class to class connection counts
    #

    def class_to_class_connections(self, **kwargs):
        """
        ``kwargs`` passed to ``filter_interclass_network``.
        """

        if 'network' not in kwargs:

            kwargs['network'] = self.get_interclass_network_df()

        network = self.filter_interclass_network(**kwargs)

        self._log('Counting connections between classes.')

        return (
            network.groupby(
                ['category_a', 'category_b', 'id_a', 'id_b']
            ).size().groupby(
                level = ['category_a', 'category_b']
            ).size()
        )


    def class_to_class_connections_undirected(self, **kwargs):

        param = {
            'only_undirected': True,
        }
        kwargs.update(param)

        c2c = self.class_to_class_connections(**kwargs)

        c2c_rev = dict(
            (
                (cls1, cls0),
                val
            )
            for (cls0, cls1), val in zip(c2c.index, c2c)
            if cls0 != cls1
        )

        return common.sum_dicts(c2c, c2c_rev)


    def class_to_class_connections_directed(self, **kwargs):

        param = {
            'only_directed': True,
        }
        kwargs.update(param)

        return self.class_to_class_connections(**kwargs)


    def class_to_class_connections_stimulatory(self, **kwargs):

        param = {
            'only_effect': 1,
        }
        kwargs.update(param)

        return self.class_to_class_connections(**kwargs)


    def class_to_class_connections_inhibitory(self, **kwargs):

        param = {
            'only_effect': -1,
        }
        kwargs.update(param)

        return self.class_to_class_connections(**kwargs)


    #
    # Inter-class degrees
    #

    def degree_inter_class_network(
            self,
            source_classes = None,
            target_classes = None,
            degrees_of = 'target',
            **kwargs
        ):
        """
        degrees_of : str
            Either *source* or *target*. Count the degrees for the source
            or the target class.
        """

        id_cols = ('id_a', 'id_b')
        groupby, unique = (
            id_cols
                if degrees_of == 'source' else
            reversed(id_cols)
        )

        degrees = (
            self.inter_class_network(
                source_classes = source_classes,
                target_classes = target_classes,
                **kwargs
            ).groupby(groupby)[unique].nunique()
        )

        return degrees[degrees != 0]


    def degree_inter_class_network_undirected(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        kwargs.update({'only_undirected': True})

        return (
            self.degree_inter_class_network(
                source_classes = source_classes,
                target_classes = target_classes,
                **kwargs
            )
        )


    def degree_inter_class_network_directed(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        kwargs.update({'only_directed': True})

        return (
            self.degree_inter_class_network(
                source_classes = source_classes,
                target_classes = target_classes,
                **kwargs
            )
        )


    def degree_inter_class_network_stimulatory(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        kwargs.update({
            'only_directed': True,
            'only_effect': 1,
        })

        return (
            self.degree_inter_class_network(
                source_classes = source_classes,
                target_classes = target_classes,
                **kwargs
            )
        )


    def degree_inter_class_network_inhibitory(
            self,
            source_classes = None,
            target_classes = None,
            **kwargs
        ):

        kwargs.update({
            'only_directed': True,
            'only_effect': -1,
        })

        return (
            self.degree_inter_class_network(
                source_classes = source_classes,
                target_classes = target_classes,
                **kwargs
            )
        )


    def degree_inter_class_network_2(
            self,
            degrees_of = 'target',
            sum_by_class = True,
            **kwargs
        ):

        if 'network' not in kwargs:

            kwargs['network'] = self.get_interclass_network_df()

        network = self.filter_interclass_network(**kwargs)

        id_cols = ('id_a', 'id_b')
        groupby, unique = (
            id_cols
                if degrees_of == 'source' else
            reversed(id_cols)
        )

        if sum_by_class:

            groupby_cat = (
                'category_a'
                    if degrees_of == 'source' else
                'category_b'
            )
            groupby = [groupby, groupby_cat]

        degrees = network.groupby(groupby)[unique].nunique()

        if sum_by_class:

            degrees = degrees.groupby(groupby_cat).sum()

        return degrees[degrees != 0]


    def degree_inter_class_network_undirected_2(self, **kwargs):

        kwargs.update({'only_undirected': True, 'degrees_of': 'source'})
        deg_source = self.degree_inter_class_network_2(**kwargs)

        kwargs.update({'only_undirected': True, 'degrees_of': 'target'})
        deg_target = self.degree_inter_class_network_2(**kwargs)

        return common.sum_dicts(deg_source, deg_target)


    def degree_inter_class_network_directed_2(self, **kwargs):

        kwargs.update({'only_directed': True})

        return self.degree_inter_class_network_2(**kwargs)


    def degree_inter_class_network_stimulatory_2(self, **kwargs):

        kwargs.update({'only_effect': 1})

        return self.degree_inter_class_network_2(**kwargs)


    def degree_inter_class_network_inhibitory_2(self, **kwargs):

        kwargs.update({'only_effect': -1})

        return self.degree_inter_class_network_2(**kwargs)

    #
    # End of wrappers
    #


    def register_network(self, network):
        """
        Sets ``network`` as the default network dataset for the instance.
        All methods afterwards will use this network.
        Also it discards the interclass network data frame if it present to
        make sure future queries will address the network registered here.
        """

        self.unset_interclass_network_df()

        self.network = self._network_df(network)


    @staticmethod
    def _network_df(network):

        return (
            network.df
                if hasattr(network, 'df') else
            network
        )


    @staticmethod
    def _filter_by_classes(annot_df, classes = None, attr = 'category'):

        if not classes:

            return annot_df

        filter_op = (
            getattr(annot_df, attr).eq
                if isinstance(classes, common.basestring) else
            getattr(annot_df, attr).isin
        )

        return annot_df[filter_op(classes)]


    def export(self, fname, **kwargs):

        self.make_df()

        self.df.to_csv(fname, **kwargs)


    def classes_by_entity(self, element, labels = False):
        """
        Returns a set of class keys with the classes containing at least
        one of the elements.

        :param str,set element:
            One or more element (entity) to search for in the classes.
        :param bool labels:
            Return labels instead of keys.
        """

        element = common.to_set(element)

        return set(
            cls.label if labels else key
            for key, cls in iteritems(self.classes)
            if element & elements
        )


    def entities_by_resource(self, entity_types = None):

        by_resource = collections.defaultdict(set)

        for key, cls in iteritems(self.classes):

            by_resource[cls.resource].update(
                cls.filter_entity_type(entity_type = entity_type)
            )

        return dict(by_resource)

    # TODO: this kind of methods should be implemented by metaprogramming
    def proteins_by_resource(self):

        return self.entities_by_resource(entity_types = 'protein')


    def complexes_by_resource(self):

        return self.entities_by_resource(entity_types = 'complex')


    def mirnas_by_resource(self):

        return self.entities_by_resource(entity_types = 'mirna')


    def counts_by_resource(self, entity_types = None):

        return dict(
            (
                resource,
                len(entities)
            )
            for resource, entities in iteritems(
                self.entities_by_resource(entity_types = entity_types)
            )
        )


    def get_entities(self, entity_types = None):

        return entity.Entity.filter_entity_type(
            set.union(*self.classes.values()),
            entity_type = entity_types,
        )


    # TODO: this kind of methods should be implemented by metaprogramming
    def get_proteins(self):

        return self.get_entities(entity_types = 'protein')


    def get_complexes(self):

        return self.get_entities(entity_types = 'complex')


    def get_mirnas(self):

        return self.get_entities(entity_types = 'mirna')


    def numof_entities(self, entity_types = None):

        return len(self.get_entities(entity_types = entity_types))


    # TODO: this kind of methods should be implemented by metaprogramming
    def numof_proteins(self):

        return self.numof_entities(entity_types = 'protein')


    def numof_complexes(self):

        return self.numof_entities(entity_types = 'complex')


    def numof_mirnas(self):

        return self.numof_entities(entity_types = 'mirna')


    def numof_classes(self):

        return len(self.classes)


    def numof_records(self, entity_types = None):

        return sum(
            cls.count_entity_type(entity_type = entity_type)
            for cls in self.classes.values()
        )


    # TODO: this kind of methods should be implemented by metaprogramming
    def numof_protein_records(self):

        return self.numof_records(entity_types = 'protein')


    def numof_complex_records(self):

        return self.numof_records(entity_types = 'complex')


    def numof_mirna_records(self):

        return self.numof_records(entity_types = 'mirna')


    def update_summaries(self):

        self.summaries = {}

        for cat, level in iteritems(self.class_types):

            if level == 'sub':

                continue

            label = self.class_labels[cat]

            self.summaries[label] = {
                'label': label,
                'level': level,
                'resources': sorted(
                    self.resource_labels[res]
                    for res in self.children[cat]
                    if res in self.resource_labels
                ),
                'n_proteins': sum(
                    1 for entity in self.classes[cat]
                    if not isinstance(entity, intera.Complex)
                ),
                'n_complexes': sum(
                    1 for entity in self.classes[cat]
                    if isinstance(entity, intera.Complex)
                ),
            }


    def summaries_tab(self, outfile = None, return_table = False):

        columns = (
            ('label', 'Category'),
            ('level', 'Category level'),
            ('n_proteins', 'Proteins'),
            ('n_complexes', 'Complexes'),
            ('resources', 'Resources'),
        )

        tab = []
        tab.append([f[1] for f in columns])

        tab.extend([
            [
                (
                    ', '.join(self.summaries[src][f[0]])
                        if isinstance(self.summaries[src][f[0]], list) else
                    str(self.summaries[src][f[0]])
                )
                for f in columns
            ]
            for src in sorted(self.summaries.keys())
        ])

        if outfile:

            with open(outfile, 'w') as fp:

                fp.write('\n'.join('\t'.join(row) for row in tab))

        if return_table:

            return tab


    def __getitem__(self, item):

        if isinstance(item, tuple) and item in self.classes:

            return self.classes[item]

        else:

            return self.classes_by_entity(item)


    def browse(
            self,
            name = None,
            parent = None,
            resource = None,
            scope = None,
            aspect = None,
            source = None,
            transmitter = None,
            receiver = None,
            **kwargs
        ):
        """
        Presents information about annotation classes as ascii tables printed
        in the terminal. If one class provided, prints one table. If multiple
        classes provided, prints a table for each of them one by one
        proceeding to the next one once you hit return. If no classes
        provided goes through all classes.

        **kwargs passed to ``pypath.utils.uniprot.info``.
        """

        classes = dict(
            (cls.label, cls)
            for cls in self.iter_classes(
                name = name,
                parent = parent,
                resource = resource,
                scope = scope,
                aspect = aspect,
                source = source,
                transmitter = transmitter,
                receiver = receiver,
                entity_type = 'protein',
            )
        )

        labels = sorted(classes.keys())
        n_classes = len(labels)

        for n, label in enumerate(labels):

            uniprots = classes[label].members

            sys.stdout.write(
                '[%u/%u] =====> %s <===== [%u proteins]\n' % (
                    n + 1,
                    n_classes,
                    label,
                    len(uniprots)
                )
            )

            utils_uniprot.info(uniprots, **kwargs)

            input()

            sys.stdout.write('\n\n')



class AnnotationBase(resource.AbstractResource):

    _dtypes = {
        'uniprot': 'category',
        'genesymbol': 'category',
        'entity_type': 'category',
        'source': 'category',
        'label': 'category',
        'value': 'object',
        'record_id': 'int32',
    }


    def __init__(
            self,
            name,
            ncbi_tax_id = 9606,
            input_method = None,
            input_args = None,
            entity_type = 'protein',
            swissprot_only = True,
            proteins = (),
            complexes = (),
            reference_set = (),
            infer_complexes = None,
            dump = None,
            primary_field = None,
            **kwargs
        ):
        """
        Represents annotations for a set of proteins.
        Loads the data from the original resource and provides methods
        to query the annotations.

        :arg str name:
            A custom name for the annotation resource.
        :arg int ncbi_tax_id:
            NCBI Taxonomy identifier.
        :arg callable,str input_method:
            Either a callable or the name of a method in the ``dataio``
            module. Should return a dict with UniProt IDs as keys or an
            object suitable for ``process_method``.
        :arg dict input_args:
            Arguments for the ``input_method``.
        """

        session_mod.Logger.__init__(self, name = 'annot')

        input_args = input_args or {}
        input_args.update(kwargs)

        resource.AbstractResource.__init__(
            self,
            name = name,
            ncbi_tax_id = ncbi_tax_id,
            input_method = input_method,
            input_args = input_args,
            dump = dump,
            data_attr_name = 'annot',
        )

        self.entity_type = entity_type
        self.primary_field = primary_field
        infer_complexes = (
            infer_complexes
                if isinstance(infer_complexes, bool) else
            settings.get('annot_infer_complexes')
        )
        self.infer_complexes = (
            infer_complexes and
            self.entity_type == 'protein'
        )
        self.proteins = proteins
        self.complexes = complexes
        self.reference_set = reference_set
        self.swissprot_only = swissprot_only
        self.load()


    def reload(self):
        """
        Reloads the object from the module level.
        """

        modname = self.__class__.__module__
        mod = __import__(modname, fromlist = [modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)


    def load(self):
        """
        Loads the annotation data by calling the input method.
        Infers annotations for complexes in the complex database if
        py:attr:``infer_complexes`` is True.
        """

        self._log('Loading annotations from `%s`.' % self.name)

        self.set_reference_set()
        resource.AbstractResource.load(self)
        self._ensure_swissprot()

        self._update_primary_field()

        if self.infer_complexes:

            self.add_complexes_by_inference()


    def _update_primary_field(self):

        self.primary_field = (
            self.primary_field or
            self.get_names()[0]
                if self.get_names() else
            None
        )


    def _ensure_swissprot(self):

        if self.entity_type == 'protein':

            new = collections.defaultdict(set)

            for uniprot, annots in iteritems(self.annot):

                swissprots = mapping.map_name(
                    uniprot,
                    'uniprot',
                    'uniprot',
                    ncbi_tax_id = self.ncbi_tax_id,
                )

                for swissprot in swissprots:

                    new[swissprot].update(annots)

            self.annot = dict(new)


    def add_complexes_by_inference(self, complexes = None):
        """
        Creates complex annotations by in silico inference and adds them
        to this annotation set.
        """

        complex_annotation = self.complex_inference(complexes = complexes)

        self.annot.update(complex_annotation)


    def complex_inference(self, complexes = None):
        """
        Annotates all complexes in `complexes`, by default in the default
        complex database (existing in the `complex` module or generated
        on demand according to the module's current settings).

        Returns
        -------
        Dict with complexes as keys and sets of annotations as values.
        Complexes with no valid information in this annotation resource
        won't be in the dict.

        Parameters
        ----------
        complexes : iterable
            Iterable yielding complexes.
        """

        self._log('Inferring complex annotations from `%s`.' % self.name)

        if not complexes:

            import pypath.core.complex as complex

            complexdb = complex.get_db()

            complexes = complexdb.complexes.values()

        complex_annotation = collections.defaultdict(set)

        for cplex in complexes:

            this_cplex_annot = self.annotate_complex(cplex)

            if this_cplex_annot is not None:

                complex_annotation[cplex].update(this_cplex_annot)

        return complex_annotation


    def annotate_complex(self, cplex):
        """
        Infers annotations for a single complex.
        """

        if (
            not all(comp in self for comp in cplex.components.keys()) or
            self._eq_fields is None
        ):
            # this means no annotation for this complex
            return None

        elif not self._eq_fields:
            # here empty set means the complex belongs
            # to the class of enitities covered by this
            # annotation
            return set()

        elif callable(self._eq_fields):

            # here a custom method combines the annotations
            # we look at all possible combinations of the annotations
            # of the components, but most likely each component have
            # only one annotation in this case
            return set(
                self._eq_fields(*annots)
                for annots in itertools.product(
                    *(
                        self.annot[comp]
                        for comp in cplex.components.keys()
                    )
                )
            )

        elif hasattr(self, '_merge'):

            return self._merge(*(
                self.annot[comp]
                for comp in cplex.components.keys()
            ))

        else:

            groups = collections.defaultdict(set)
            empty_args = {}
            cls = None
            components = set(cplex.components.keys())

            for comp in cplex.components.keys():

                for comp_annot in self.annot[comp]:

                    if cls is None:

                        cls = comp_annot.__class__
                        empty_args = dict(
                            (f, None)
                            for f in comp_annot._fields
                            if f not in self._eq_fields
                        )

                    groups[
                        tuple(
                            getattr(comp_annot, f)
                            for f in self._eq_fields
                        )
                    ].add(comp)

            return set(
                # the characteristic attributes of the group
                # and the remaining left empty
                cls(
                    **dict(zip(self._eq_fields, key)),
                    **empty_args
                )
                # checking all groups
                for key, group in iteritems(groups)
                # and accepting the ones covering all members of the complex
                if group == components
            ) or None


    def _update_complex_attribute_classes(self):

        complex.ComplexAggregator._update_complex_attribute_classes_static(
            self.annot.keys(),
            mod = sys.modules[__name__],
        )


    def load_proteins(self):
        """
        Retrieves a set of all UniProt IDs to have a base set of the entire
        proteome.
        """

        self.uniprots = set(dataio.all_uniprots(organism = self.ncbi_tax_id))


    @staticmethod
    def get_reference_set(
            proteins = (),
            complexes = (),
            use_complexes = False,
            ncbi_tax_id = 9606,
            swissprot_only = True,
        ):
        """
        Retrieves the reference set i.e. the set of all entities which
        potentially have annotation in this resource. Typically this is the
        proteome of the organism from UniProt optionally with all the protein
        complexes from the complex database.
        """

        proteins = (
            proteins or
            sorted(
                dataio.all_uniprots(
                    organism = ncbi_tax_id,
                    swissprot = swissprot_only,
                )
            )
        )

        if use_complexes:

            import pypath.core.complex as complex

            complexes = (
                complexes or
                sorted(complex.all_complexes())
            )

        reference_set = sorted(
            itertools.chain(
                proteins,
                complexes,
            )
        )

        return proteins, complexes, reference_set


    def _get_reference_set(self):

        return self.get_reference_set(
            proteins = self.proteins,
            complexes = self.complexes,
            use_complexes = self.has_complexes(),
            ncbi_tax_id = self.ncbi_tax_id,
            swissprot_only = self.swissprot_only,
        )


    def set_reference_set(self):
        """
        Assigns the reference set to the :py:attr``reference_set`` attribute.
        The reference set is the set of all entities which
        potentially have annotation in this resource. Typically this is the
        proteome of the organism from UniProt optionally with all the protein
        complexes from the complex database.
        """

        if not self.reference_set:

            proteins, complexes, reference_set = self._get_reference_set()

            self.proteins = proteins
            self.complexes = complexes
            self.reference_set = reference_set


    def has_complexes(self):

        return self.entity_type == 'complex' or self.infer_complexes


    def _process_method(self, *args, **kwargs):
        """
        By default it converts a set to dict of empty sets in order to make
        it compatible with other methods.
        Derived classes might override.
        """

        self.annot = dict((u, set()) for u in self.data)


    def select(self, method = None, **kwargs):
        """
        Retrieves a subset by filtering based on ``kwargs``.
        Each argument should be a name and a value or set of values.
        Elements having the provided values in the annotation will be
        returned.
        Returns a set of UniProt IDs.
        """

        result = set()
        
        names = set(self.get_names())
        
        if not all(k in names for k in kwargs.keys()):
            
            raise ValueError('Unknown field names: %s' % (
                    ', '.join(sorted(set(kwargs.keys()) - names))
                )
            )

        for uniprot, annot in iteritems(self.annot):

            for a in annot:

                # we either call a method on all records
                # or check against conditions provided in **kwargs
                if (
                    not callable(method) or
                    method(a)
                ) and all(
                    (
                        # simple agreement
                        (
                            getattr(a, name) == value
                        )
                        # custom method returns bool
                        or
                        (
                            callable(value)
                            and
                            value(getattr(a, name))
                        )
                        # multiple value in annotation slot
                        # and value is a set: checking if they have
                        # any in common
                        or
                        (
                            isinstance(getattr(a, name), common.list_like)
                            and
                            isinstance(value, set)
                            and
                            set(getattr(a, name)) | value
                        )
                        # search value is a set, checking if contains
                        # the record's value
                        or
                        (
                            isinstance(value, set)
                            and
                            getattr(a, name) in value
                        )
                        # record's value contains multiple elements
                        # (set, list or tuple), checking if it contains
                        # the search value
                        or
                        (
                            isinstance(getattr(a, name), common.list_like)
                            and
                            value in getattr(a, name)
                        )
                    )
                    for name, value in iteritems(kwargs)
                ):

                    result.add(uniprot)
                    break

        return result


    # synonym for old name
    get_subset = select


    def labels(self, method = None, **kwargs):
        """
        Same as ``select`` but returns a list of labels (more human readable).
        """

        return mapping.label(self.select(method = method, **kwargs))


    def show(self, method = None, table_param = None, **kwargs):
        """
        Same as ``select`` but prints a table to the console with basic
        information from the UniProt datasheets.
        """

        table_param = table_param or {}

        utils_uniprot.info(
            *self.select(method = method, **kwargs),
            **table_param
        )


    def get_subset_bool_array(self, reference_set = None, **kwargs):
        """
        Returns a boolean vector with True and False values for each entity
        in the reference set. The values represent presence absence data
        in the simplest case, but by providing **kwargs any kind of matching
        and filtering is possible. **kwargs are passed to the ``select``
        method.
        """

        reference_set = reference_set or self.reference_set

        subset = self.get_subset(**kwargs)

        return np.array([
            entity in subset
            for entity in reference_set
        ])


    def to_bool_array(self, reference_set):
        """
        Returns a presence/absence boolean array for a reference set.
        """

        total = self.to_set()

        return np.array([
            entity in total
            for entity in reference_set
        ])


    def to_set(self):
        """
        Returns the entities present in this annotation resource as a set.
        """

        return set(self.annot.keys())


    @staticmethod
    def _entity_types(entity_types):

        return (
            {entity_types}
                if isinstance(entity_types, common.basestring) else
            entity_types
        )


    def all_entities(self, entity_types = None):
        """
        All entities annotated in this resource.
        """

        entity_types = self._entity_types(entity_types)

        return sorted((
            k for k in self.annot.keys()
            if self._match_entity_type(k, entity_types)
        ))


    def all_proteins(self):
        """
        All UniProt IDs annotated in this resource.
        """

        return sorted((
            k for k in self.annot.keys()
            if self.is_protein(k)
        ))


    def all_complexes(self):
        """
        All protein complexes annotated in this resource.
        """

        return sorted((
            k
            for k in self.annot.keys()
            if self.is_complex(k)
        ))


    def all_mirnas(self):
        """
        All miRNAs annotated in this resource.
        """

        return sorted((
            k for k in self.annot.keys()
            if self.is_mirna(k)
        ))


    @staticmethod
    def is_protein(key):

        return entity.Entity._is_protein(key)


    @staticmethod
    def is_mirna(key):

        return entity.Entity._is_mirna(key)


    @staticmethod
    def is_complex(key):

        return entity.Entity._is_complex(key)


    @classmethod
    def get_entity_type(cls, key):

        return entity.Entity._get_entity_type(key)


    @classmethod
    def _match_entity_type(cls, key, entity_types):

        return not entity_types or cls.get_entity_type(key) in entity_types


    def numof_records(self, entity_types = None):
        """
        The total number of annotation records.
        """

        entity_types = self._entity_types(entity_types)

        return sum(
            max(len(a), 1)
            for k, a in iteritems(self.annot)
            if self._match_entity_type(k, entity_types)
        )


    def numof_protein_records(self):

        return self.numof_records(entity_types = {'protein'})


    def numof_mirna_records(self):

        return self.numof_records(entity_types = {'mirna'})


    def numof_complex_records(self):

        return self.numof_records(entity_types = {'complex'})


    def numof_entities(self):
        """
        The number of annotated entities in the resource.
        """

        return len(self.annot)


    def _numof_entities(self, entity_types = None):

        entity_types = self._entity_types(entity_types)

        return len([
            k for k in self.annot.keys()
            if self._match_entity_type(k, entity_types)
        ])


    def numof_proteins(self):

        return self._numof_entities(entity_types = {'protein'})


    def numof_mirnas(self):

        return self._numof_entities(entity_types = {'mirna'})


    def numof_complexes(self):

        return self._numof_entities(entity_types = {'complex'})


    def __repr__(self):

        return (
            '<%s annotations: %u records about %u entities>' % (
                self.name,
                self.numof_records(),
                self.numof_entities(),
            )
        )


    def to_array(self, reference_set = None, use_fields = None):
        """
        Returns an entity vs feature array. In case of more complex
        annotations this might be huge.
        """

        use_fields = (
            use_fields or (
                default_fields[self.name]
                    if self.name in default_fields else
                None
            )
        )

        self._log(
            'Creating boolean array from `%s` annotation data.' % self.name
        )

        reference_set = reference_set or self.reference_set

        all_fields = self.get_names()
        fields = use_fields or all_fields
        ifields = tuple(
            i for i, field in enumerate(all_fields) if field in fields
        )
        result = [
            (
                (self.name,),
                self.to_bool_array(reference_set = reference_set)
            )
        ]

        for i in xrange(len(fields)):

            this_ifields = ifields[:i + 1]
            this_fields  =  fields[:i + 1]

            value_combinations = set(
                tuple(annot[j] for j in this_ifields)
                for annots in self.annot.values()
                for annot in annots
            )
            value_combinations = sorted(
                values
                for values in value_combinations
                if not any(
                    isinstance(v, (type(None), float, int))
                    for v in values
                )
            )

            for values in value_combinations:

                labels = tuple(
                    'not-%s' % this_fields[ival]
                        if isinstance(val, bool) and not val else
                    this_fields[ival]
                        if isinstance(val, bool) and val else
                    val
                    for ival, val in enumerate(values)
                )

                this_values = dict(zip(this_fields, values))

                this_array = self.get_subset_bool_array(
                    reference_set = reference_set,
                    **this_values
                )

                result.append(
                    (
                        (self.name,) + labels,
                        this_array,
                    )
                )

        self._log(
            'Boolean array has been created from '
            '`%s` annotation data.' % self.name
        )

        return (
            tuple(r[0] for r in result),
            np.vstack([r[1] for r in result]).T
        )


    @property
    def has_fields(self):

        return any(self.annot.values())


    def make_df(self, rebuild = False):
        """
        Compiles a ``pandas.DataFrame`` from the annotation data.
        The data frame will be assigned to :py:attr``df``.
        """

        self._log('Creating dataframe from `%s` annotations.' % self.name)

        if hasattr(self, 'df') and not rebuild:

            self._log('Data frame already exists, rebuild not requested.')
            return

        discard = {'n/a', None}

        columns = [
            'uniprot',
            'genesymbol',
            'entity_type',
            'source',
            'label',
            'value',
            'record_id',
        ]

        has_fields = self.has_fields
        records = []
        irec = 0

        for element, annots in iteritems(self.annot):

            if not element:

                continue

            genesymbol_str = (
                'COMPLEX:%s' % element.genesymbol_str
                    if hasattr(element, 'genesymbol_str') else
                'COMPLEX:%s' % (
                    complex.get_db().complexes[element].genesymbol_str
                )
                    if element.startswith('COMPLEX:') else
                (
                    mapping.map_name0(element, 'uniprot', 'genesymbol') or
                    ''
                )
            )

            if not has_fields:

                records.append([
                    element.__str__(),
                    genesymbol_str,
                    self.get_entity_type(element),
                    self.name,
                    'in %s' % self.name,
                    'yes',
                    irec,
                ])

                irec += 1

            for annot in annots:

                for label, value in zip(annot._fields, annot):

                    if value in discard:

                        continue

                    if isinstance(value, (set, list, tuple)):

                        value = ';'.join(map(str, value))

                    records.append([
                        element.__str__(),
                        genesymbol_str,
                        self.get_entity_type(element),
                        self.name,
                        label,
                        str(value),
                        irec,
                    ])

                irec += 1

        self.df = pd.DataFrame(
            records,
            columns = columns,
        ).astype(self._dtypes)


    def coverage(self, other):
        """
        Calculates the coverage of the annotation i.e. the proportion of
        entities having at least one record in this annotation resource
        for an arbitrary set of entities.
        """

        other = other if isinstance(other, set) else set(other)

        return len(self & other) / len(self)


    def proportion(self, other):

        other = other if isinstance(other, set) else set(other)

        return len(self & other) / len(other) if other else .0


    def subset_intersection(self, universe, **kwargs):
        """
        Calculates the proportion of entities in a subset occuring in the
        set ``universe``. The subset is selected by passing **kwargs to the
        ``select`` method.
        """

        subset = self.get_subset(**kwargs)

        return len(subset & universe) / len(subset)


    def get_values(self, name, exclude_none = True):
        """
        Returns the set of all possible values of a field. E.g. if the
        records of this annotation have a field ``cell_type`` then calling
        this method can tell you that across all records the values of
        this field might be ``{'macrophage', 'epithelial_cell', ...}``.
        """

        values =  {
            val
            for aset in self.annot.values()
            for a in aset
            for val in (
                # to support tuple values
                getattr(a, name)
                    if isinstance(getattr(a, name), common.list_like) else
                (getattr(a, name),)
            )
        }

        if exclude_none:

            values.discard(None)

        return values


    def get_names(self):
        """
        Returns the list of field names in the records. The annotation
        consists of uniform records and each entity might be annotated
        with one or more records. Each record is a tuple of fields, for
        example ``('cell_type', 'expression_level', 'score')``.
        """

        names = ()

        for values in self.annot.values():

            if values:

                for val in values:

                    names = val._fields
                    break

            break

        return names


    def __and__(self, other):

        return other & self.to_set()


    def __or__(self, other):

        return other | self.to_set()


    def __sub__(self, other):

        return self.to_set() - other


    def __len__(self):

        return self.numof_entities()


    def __getitem__(self, item):

        if not isinstance(item, common.simple_types):

            return set.union(
                *(
                    self.annot[it]
                    for it in item
                    if it in self
                )
            )

        elif item in self:

            return self.annot[item]

        elif self.primary_field:

            return self.select(**{self.primary_field: item})


    def __contains__(self, item):

        return item in self.annot


    def numof_references(self):
        """
        Some annotations contain references. The field name for references
        is always ``pmid`` (PubMed ID). This method collects and counts the
        references across all records.
        """

        return len(set(self.all_refs()))


    def curation_effort(self):
        """
        Counts the reference-record pairs.
        """

        return len(self.all_refs())


    def all_refs(self):
        """
        Some annotations contain references. The field name for references
        is always ``pmid`` (PubMed ID). This method collects the references
        across all records. Returns *list*.
        """

        if 'pmid' in self.get_names():

            return [
                a.pmid
                for aa in self.annot.values()
                for a in aa
                if a.pmid
            ]

        return []


    @property
    def summary(self):

        return {
            'n_total': self.numof_entities(),
            'n_records_total': self.numof_records(),
            'n_proteins': self.numof_proteins(),
            'pct_proteins': self.proportion(self.proteins) * 100,
            'n_complexes': self.numof_complexes(),
            'pct_complexes': self.proportion(
                complex.get_db().complexes.keys()
            ) * 100,
            'n_mirnas': self.numof_mirnas(),
            'pct_mirnas': (
                self.proportion(reflists.get_reflist('mirbase')) * 100
            ),
            'n_protein_records': self.numof_protein_records(),
            'n_complex_records': self.numof_complex_records(),
            'n_mirna_records': self.numof_mirna_records(),
            'references': self.numof_references(),
            'curation_effort': self.curation_effort(),
            'records_per_entity': (
                self.numof_protein_records() / self.numof_proteins()
                    if self.numof_proteins() else
                self.numof_records() / self.numof_entities()
                    if self.numof_entities() else
                0
            ),
            'complex_annotations_inferred': bool(self.numof_proteins()),
            'fields': ', '.join(self.get_names()),
            'name': self.name,
        }


    def browse(self, field = None, start = 0, **kwargs):
        """
        Presents information about annotation categories as ascii tables
        printed in the terminal.
        If one category provided, prints one table. If multiple
        categories provided, prints a table for each of them one by one
        proceeding to the next one once you hit return. If no categories
        provided goes through all levels of the primary category.
        
        :param NoneType,str,list,dict field:
            The field to browse categories by.
            * If None the primary field will be selected.
              If this annotation resource doesn't have fields, all proteins
              will be presented as one single category.
            * If a string it will be considered a field name and it will
              browse through all levels of this field.
            * If a list, set or tuple, it will be considered either a list
              of field names or a list of values from the primary field.
              In the former case all combinations of the values of the
              fields will be presented, in the latter case the browsing
              will be limited to the levels of the primary field contained
              in ``field``.
            * If a dict, keys are supposed to be field names and values
              as list of levels. If any of the values are None, all levels
              from that field will be used.
        :param int start:
            Start browsing from this category. E.g. if there are 500
            categories and start is 250 it will skip everything before the
            250th.
        **kwargs passed to ``pypath.utils.uniprot.info``.
        """
        
        if not field and not self.primary_field:
            
            uniprots = entity.Entity.only_proteins(self.to_set())
            
            utils_uniprot.info(uniprots, **kwargs)
            
            return
        
        field = field or self.primary_field
        
        if isinstance(field, common.basestring):
            
            # all values of the field
            field = {field: self.get_values(field)}
            
        elif isinstance(field, common.list_like):
            
            if set(field) & set(self.get_names()):
                
                # a set of fields provided
                field = dict(
                    (
                        fi,
                        self.get_values(fi)
                    )
                    for fi in field
                )
                
            else:
                
                # a set of values provided
                field = {self.primary_field: field}
            
        elif isinstance(field, dict):
            
            field = dict(
                (
                    fi,
                    vals or self.get_values(fi)
                )
                for fi, vals in iteritems(field)
            )
            
        else:
            
            sys.stdout.write(
                'Could not recognize field definition, '
                'please refer to the docs.\n'
            )
            sys.stdout.flush()
            return
        
        # otherwise we assume `field` is a dict of fields and values
        
        field_keys = list(field.keys())
        field_values = [field[k] for k in field_keys]
        
        values = sorted(itertools.product(*field_values))
        total = len(values)
        
        for n, vals in enumerate(values):
            
            if n + 1 < start:
                
                continue
            
            args = dict(zip(field_keys, vals))
            
            proteins = entity.Entity.only_proteins(self.select(**args))
            
            if not proteins:
                
                continue
            
            label = (
                vals[0]
                    if len(vals) == 1 else
                ', '.join(
                    '%s: %s' % (
                        key,
                        str(val)
                    )
                    for key, val in iteritems(args)
                )
            )
            
            sys.stdout.write(
                '[%u/%u] =====> %s <===== [%u proteins]\n' % (
                    n + 1,
                    total or 0,
                    label,
                    len(proteins)
                )
            )
            
            utils_uniprot.info(proteins, **kwargs)
            
            input()
            
            sys.stdout.write('\n\n')


class Membranome(AnnotationBase):

    _eq_fields = ('membrane', 'side')


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Membranome',
            input_method = 'membranome_annotations',
            **kwargs
        )


    def _process_method(self):

        record = collections.namedtuple(
            'MembranomeAnnotation',
            ['membrane', 'side'],
        )

        _annot = collections.defaultdict(set)

        for a in self.data:

            _annot[a[0]].add(record(a[1], a[2]))

        self.annot = dict(_annot)


class Exocarta(AnnotationBase):

    _eq_fields = ('tissue', 'vesicle')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        if 'database' not in kwargs:

            kwargs['database'] = 'exocarta'

        AnnotationBase.__init__(
            self,
            name = kwargs['database'].capitalize(),
            ncbi_tax_id = ncbi_tax_id,
            input_method = '_get_exocarta_vesiclepedia',
            **kwargs,
        )


    def _process_method(self):

        record = collections.namedtuple(
            '%sAnnotation' % self.name,
            ['pmid', 'tissue', 'vesicle'],
        )

        _annot = collections.defaultdict(set)

        missing_name = False

        for a in self.data:

            if not a[1]:

                missing_name = True
                continue

            uniprots = mapping.map_name(a[1], 'genesymbol', 'uniprot')

            for u in uniprots:

                for vesicle in (
                    a[3][3]
                        if self.name == 'Vesiclepedia' else
                    ('Exosomes',)
                ):

                    _annot[u].add(record(a[3][0], a[3][2], vesicle))

        self.annot = dict(_annot)

        if missing_name:

            self._log(
                'One or more names were missing while processing '
                'annotations from %s. Best if you check your cache '
                'file and re-download the data if it\' corrupted.' % (
                    self.name
                )
            )


class Vesiclepedia(Exocarta):

    _eq_fields = ('tissue', 'vesicle')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        Exocarta.__init__(
            self,
            ncbi_tax_id = ncbi_tax_id,
            database = 'vesiclepedia',
            **kwargs
        )


class Embrace(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'EMBRACE',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'embrace.embrace_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Baccin2019(AnnotationBase):

    _eq_fields = ('mainclass', 'subclass', 'location')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Baccin2019',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'baccin2019.baccin2019_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Almen2009(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Almen2019',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'almen2009.almen2009_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Italk(AnnotationBase):

    _eq_fields = ('mainclass', 'subclass')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'iTALK',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'italk.italk_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Cellcellinteractions(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'CellCellInteractions',
            ncbi_tax_id = ncbi_tax_id,
            input_method = (
                'cellcellinteractions.'
                'cellcellinteractions_annotations'
            ),
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Matrisome(AnnotationBase):

    _eq_fields = ('mainclass', 'subclass')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'Matrisome',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'matrisome_annotations',
            **kwargs,
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Surfaceome(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Surfaceome',
            input_method = 'surfaceome_annotations',
            **kwargs
        )


    def _process_method(self):

        _annot = collections.defaultdict(set)

        record = collections.namedtuple(
            'SurfaceomeAnnotation',
            ['score', 'mainclass', 'subclasses']
        )
        record.__defaults__ = (None, None)

        for uniprot, a in iteritems(self.data):

            _annot[uniprot].add(
                record(
                    a[0],
                    a[1],
                    tuple(sorted(a[2])) if a[2] else None,
                )
            )

        self.annot = dict(_annot)


class Adhesome(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Adhesome',
            input_method = 'adhesome.adhesome_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Cancersea(AnnotationBase):

    _eq_fields = ('state',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'CancerSEA',
            input_method = 'cancersea_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Hgnc(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'HGNC',
            input_method = 'hgnc_genegroups',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')



class Zhong2015(AnnotationBase):

    _eq_fields = ('type',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Zhong2015',
            input_method = 'zhong2015_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Opm(AnnotationBase):

    _eq_fields = ('membrane',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'OPM',
            input_method = 'opm_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Phobius(AnnotationBase):

    _eq_fields = (
        'tm_helices',
        'signal_peptide',
        'cytoplasmic',
        'non_cytoplasmic',
    )


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Phobius',
            input_method = 'phobius.phobius_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Topdb(AnnotationBase):

    _eq_fields = ('membrane',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'TopDB',
            input_method = 'topdb_annotations',
            input_args = {
                'ncbi_tax_id': ncbi_tax_id,
            },
            ncbi_tax_id = ncbi_tax_id,
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Cpad(AnnotationBase):

    _eq_fields = (
        'effect_on_pathway',
        'pathway',
        'effect_on_cancer',
        'cancer' ,
    )


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'CPAD',
            input_method = 'cpad_annotations',
            ncbi_tax_id = ncbi_tax_id,
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Disgenet(AnnotationBase):

    _eq_fields = (
        'disease',
    )


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'DisGeNet',
            input_method = 'disgenet_annotations',
            ncbi_tax_id = ncbi_tax_id,
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Msigdb(AnnotationBase):

    _eq_fields = (
        'collection',
        'geneset',
    )


    def __init__(self, ncbi_tax_id = 9606, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'MSigDB',
            input_method = 'msigdb_annotations',
            ncbi_tax_id = ncbi_tax_id,
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Integrins(AnnotationBase):

    _eq_fields = ()


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Integrins',
            input_method = 'get_integrins',
            **kwargs
        )


class Lrdb(AnnotationBase):


    _eq_fields = ('role',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'LRdb',
            input_method = 'lrdb.lrdb_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class HumanProteinAtlas(AnnotationBase):

    _eq_fields = ('organ', 'tissue', 'status', 'level', 'pathology')


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'HPA_tissue',
            input_method = 'proteinatlas_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class HumanProteinAtlasSubcellular(AnnotationBase):

    _eq_fields = ('location',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'HPA_subcellular',
            input_method = 'proteinatlas_subcellular_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class HumanProteinAtlasSecretome(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'HPA_secretome',
            input_method = 'proteinatlas_secretome_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')



class CancerGeneCensus(AnnotationBase):

    _eq_fields = None


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'CancerGeneCensus',
            input_method = 'cancer_gene_census_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Intogen(AnnotationBase):

    _eq_fields = ('type', 'role')


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'IntOGen',
            input_method = 'intogen_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Comppi(AnnotationBase):

    _eq_fields = ('location',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'ComPPI',
            input_method = 'comppi_locations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class Ramilowski2015Location(AnnotationBase):

    _eq_fields = ('location',)


    def __init__(self, **kwargs):

        AnnotationBase.__init__(
            self,
            name = 'Ramilowski_location',
            input_method = 'ramilowski_locations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class CellSurfaceProteinAtlas(AnnotationBase):


    _eq_fields = ('high_confidence', 'tm', 'gpi', 'uniprot_cell_surface')


    def __init__(
            self,
            ncbi_tax_id = 9606,
            **kwargs
        ):
        """
        The name of this resource abbreviated as `CSPA`.
        """

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'CSPA',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'cspa.cspa_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')


class CellSurfaceProteinAtlasCellType(AnnotationBase):


    _eq_fields = ('cell_type',)


    def __init__(
            self,
            ncbi_tax_id = 9606,
            **kwargs
        ):
        """
        The name of this resource abbreviated as `CSPA`.
        """

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'CSPA_celltype',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'cspa.cspa_cell_type_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        delattr(self, 'data')



class HumanPlasmaMembraneReceptome(AnnotationBase):

    _eq_fields = ('role',)


    def __init__(self, **kwargs):
        """
        The name of this resource abbreviated as `HPMR`.
        """

        AnnotationBase.__init__(
            self,
            name = 'HPMR',
            input_method = 'hpmr_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        del self.data


class Kinasedotcom(AnnotationBase):

    _eq_fields = ('group', 'family')


    def __init__(self, **kwargs):
        """
        Kinases from `kinase.com`.
        """

        AnnotationBase.__init__(
            self,
            name = 'kinase.com',
            input_method = 'kinasedotcom_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class Tfcensus(AnnotationBase):

    _eq_fields = ()


    def __init__(self, **kwargs):
        """
        Transcription factors from TF census (Vaquerizas et al 2009).
        """

        AnnotationBase.__init__(
            self,
            name = 'TFcensus',
            input_method = 'get_tfcensus',
            **kwargs
        )


class Dgidb(AnnotationBase):

    _eq_fields = ('category',)


    def __init__(self, **kwargs):
        """
        Druggable proteins from DGIdb (Drug Gene Interaction Database).
        """

        AnnotationBase.__init__(
            self,
            name = 'DGIdb',
            input_method = 'dgidb_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class Phosphatome(AnnotationBase):

    _eq_fields = ()


    def __init__(self, **kwargs):
        """
        The list of phosphatases from Chen et al, Science Signaling (2017)
        Table S1.
        """

        AnnotationBase.__init__(
            self,
            name = 'Phosphatome',
            input_method = 'phosphatome_annotations',
            **kwargs
        )


    def _process_method(self):

        self.annot = self.data
        del self.data


class Matrixdb(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Protein annotations from MatrixDB.
        """

        AnnotationBase.__init__(
            self,
            name = 'MatrixDB',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'matrixdb_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class SignorPathways(AnnotationBase):

    _eq_fields = ('pathway',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Pathway annotations from Signor.
        """

        AnnotationBase.__init__(
            self,
            name = 'SIGNOR',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'signor_pathway_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class SignalinkPathways(AnnotationBase):

    _eq_fields = ('pathway',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Pathway annotations from SignaLink.
        """

        AnnotationBase.__init__(
            self,
            name = 'SignaLink_pathway',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'signalink.signalink_pathway_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class SignalinkFunctions(AnnotationBase):

    _eq_fields = ('function',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Functional annotations from SignaLink.
        """

        AnnotationBase.__init__(
            self,
            name = 'SignaLink_function',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'signalink.signalink_function_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class KeggPathways(AnnotationBase):

    _eq_fields = ('pathway',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Pathway annotations from KEGG.
        """

        AnnotationBase.__init__(
            self,
            name = 'KEGG',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'kegg_pathway_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class NetpathPathways(AnnotationBase):

    _eq_fields = ('pathway',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Pathway annotations from NetPath.
        """

        AnnotationBase.__init__(
            self,
            name = 'NetPath',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'netpath.netpath_pathway_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')



class Locate(AnnotationBase):

    _eq_fields = ('location',)


    def __init__(
            self,
            ncbi_tax_id = 9606,
            literature = True,
            external = True,
            predictions = False,
            **kwargs
        ):

        input_args = {
            'organism': ncbi_tax_id or 9606,
            'literature': literature,
            'external': external,
            'predictions': predictions,
        }

        AnnotationBase.__init__(
            self,
            name = 'LOCATE',
            input_method = 'locate_localizations',
            ncbi_tax_id = ncbi_tax_id,
            input_args = input_args,
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class GOCustomIntercell(go.GOCustomAnnotation):


    def __init__(
            self,
            categories = None,
            go_annot = None,
            ncbi_tax_id = 9606,
            **kwargs
        ):
        """
        Same as :class:``pypath.go.GOCustomAnnotation``
        initialized with the categories defined in
        ``pypath.intercell_annot.intercell_categories``.
        """

        categories = categories or intercell_annot.go_combined_classes

        go.GOCustomAnnotation.__init__(
            self,
            categories = categories,
            go_annot = go_annot,
            ncbi_tax_id = ncbi_tax_id,
        )


class GOIntercell(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(
            self,
            categories = None,
            go_annot = None,
            ncbi_tax_id = 9606,
            **kwargs
        ):
        """
        Annotation of proteins based on their roles in intercellular
        communication from Gene Ontology.
        """

        self.categories = categories
        self.go_annot = go_annot

        AnnotationBase.__init__(
            self,
            name = 'GO_Intercell',
            ncbi_tax_id = ncbi_tax_id,
            **kwargs
        )


    def load(self):

        record = collections.namedtuple(
            'GOIntercellAnnotation',
            ('mainclass',),
        )

        annot = GOCustomIntercell(
            categories = self.categories,
            go_annot = self.go_annot,
            ncbi_tax_id = self.ncbi_tax_id,
        )

        annot_uniprots = annot.get_annotations()

        _annot = collections.defaultdict(set)

        for mainclass, uniprots in iteritems(annot_uniprots):

            for uniprot in uniprots:

                _annot[uniprot].add(record(mainclass = mainclass))

        self.annot = dict(_annot)


    def _process_method(self, *args, **kwargs):

        pass


class CellPhoneDB(AnnotationBase):


    record = cellphonedb.CellPhoneDBAnnotation


    def __init__(self, **kwargs):

        _ = kwargs.pop('ncbi_tax_id', None)

        AnnotationBase.__init__(
            self,
            name = 'CellPhoneDB',
            input_method = 'cellphonedb.cellphonedb_protein_annotations',
            ncbi_tax_id = 9606,
            **kwargs
        )


    def _process_method(self, *args, **kwargs):

        self.annot = dict(
            (uniprot, {annot, })
            for uniprot, annot in
            iteritems(self.data)
        )


    def _eq_fields(self, *args):

        return self.record(
            *tuple(
                all(a)
                    if all(isinstance(aa, bool) for aa in a) else
                tuple(sorted(set(
                    itertools.chain(*a)
                )))
                for a in zip(*args)
            )
        )


class Icellnet(AnnotationBase):

    _eq_fields = ('role',)


    def __init__(self, **kwargs):

        _ = kwargs.pop('ncbi_tax_id', None)

        AnnotationBase.__init__(
            self,
            name = 'ICELLNET',
            input_method = 'icellnet.icellnet_annotations',
            ncbi_tax_id = 9606,
            complexes = False,
        )


    def _process_method(self, *args, **kwargs):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class IcellnetComplex(AnnotationBase):

    _eq_fields = ('role',)


    def __init__(self, **kwargs):

        _ = kwargs.pop('ncbi_tax_id', None)

        AnnotationBase.__init__(
            self,
            name = 'ICELLNET_complex',
            input_method = 'icellnet.icellnet_annotations',
            ncbi_tax_id = 9606,
            entity_type = 'complex',
        )


    def _process_method(self, *args, **kwargs):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class CellPhoneDBComplex(CellPhoneDB):


    def __init__(self, **kwargs):

        _ = kwargs.pop('ncbi_tax_id', None)

        AnnotationBase.__init__(
            self,
            name = 'CellPhoneDB_complex',
            input_method = 'cellphonedb.cellphonedb_complex_annotations',
            ncbi_tax_id = 9606,
            entity_type = 'complex',
            **kwargs
        )


class HpmrComplex(AnnotationBase):


    def __init__(self, **kwargs):

        _ = kwargs.pop('ncbi_tax_id', None)

        AnnotationBase.__init__(
            self,
            name = 'HPMR_complex',
            input_method = 'hpmr_complexes',
            ncbi_tax_id = 9606,
            entity_type = 'complex',
            **kwargs
        )


    def _process_method(self, *args, **kwargs):

        self.annot = dict(
            (cplex.__str__(), set())
            for cplex in self.data
        )
        del self.data


class Corum(AnnotationBase):


    def __init__(self, name, annot_attr, **kwargs):

        self._annot_attr = annot_attr

        AnnotationBase.__init__(
            self,
            name = name,
            input_method = 'corum_complexes',
            entity_type = 'complex',
            **kwargs
        )


    def _process_method(self, *args, **kwargs):

        record = CorumAnnotation = (
            collections.namedtuple(
                'CorumAnnotation%s' % self._annot_attr.capitalize(),
                (self._annot_attr,),
            )
        )

        self.annot = dict(
            (
                cplex.__str__(),
                set(
                    record(annot_val)
                    for annot_val in cplex.attrs[self._annot_attr]
                    if annot_val != 'None'
                )
            )
            for cplex in self.data.values()
        )

        del self.data


class CorumFuncat(Corum):


    def __init__(self, **kwargs):

        Corum.__init__(
            self,
            name = 'CORUM_Funcat',
            annot_attr = 'funcat',
            **kwargs
        )


class CorumGO(Corum):


    def __init__(self, **kwargs):

        Corum.__init__(
            self,
            name = 'CORUM_GO',
            annot_attr = 'go',
            **kwargs
        )


class LigandReceptor(AnnotationBase):

    _eq_fields = ('mainclass',)


    def __init__(
            self,
            name,
            ligand_col = None,
            receptor_col = None,
            ligand_id_type = None,
            receptor_id_type = None,
            record_processor_method = None,
            record_extra_fields = None,
            record_defaults = None,
            extra_fields_methods = None,
            **kwargs
        ):

        self.name = name
        self.ligand_col = ligand_col
        self.receptor_col = receptor_col
        self.ligand_id_type = ligand_id_type
        self.receptor_id_type = receptor_id_type
        self._record_extra_fields = record_extra_fields or ()
        self._record_defaults = record_defaults or ()
        self._extra_fields_methods = extra_fields_methods or {}
        self._set_record_template()
        self.record_processor_method = (
            record_processor_method or
            self._default_record_processor
        )

        if 'ncbi_tax_id' not in kwargs:

            kwargs['ncbi_tax_id'] = 9606

        AnnotationBase.__init__(
            self,
            name = self.name,
            **kwargs
        )


    def _set_record_template(self):

        self.record = collections.namedtuple(
            '%sAnnotation' % self.name,
            ('mainclass',) + self._record_extra_fields,
        )
        self.record.__new__.__defaults__ = () + self._record_defaults


    def _default_record_processor(self, record, typ, annot):

        i_id = self.ligand_col if typ == 'ligand' else self.receptor_col
        id_type = (
            self.ligand_id_type if typ == 'ligand' else self.receptor_id_type
        )
        original_id = record[i_id]
        uniprots = mapping.map_name(original_id, id_type, 'uniprot')

        for uniprot in uniprots:

            annot[uniprot].add(
                self.record(
                    mainclass = typ,
                    **self._get_extra_fields(record)
                )
            )


    def _get_extra_fields(self, record):

        return dict(
            (
                name,
                method(record),
            )
            for name, method in iteritems(self._extra_fields_methods)
        )


    def _process_method(self, *args, **kwargs):

        annot = collections.defaultdict(set)

        for record in self.data:

            self.record_processor_method(
                record,
                typ = 'ligand',
                annot = annot,
            )
            self.record_processor_method(
                record,
                typ = 'receptor',
                annot = annot,
            )

        self.annot = dict(annot)


class Ramilowski2015(LigandReceptor):


    def __init__(self, load_sources = False, **kwargs):

        extra_fields_methods = {
            'sources':
                lambda record: (
                    tuple(record[3].split(';')) if load_sources else None
                ),
        }


        LigandReceptor.__init__(
            self,
            name = 'Ramilowski2015',
            input_method = 'ramilowski2015.ramilowski_interactions',
            record_extra_fields = ('sources',),
            extra_fields_methods = extra_fields_methods,
            ligand_col = 0,
            receptor_col = 1,
            ligand_id_type = 'genesymbol',
            receptor_id_type = 'genesymbol',
            **kwargs
        )


class Kirouac2010(LigandReceptor):


    def __init__(self, load_sources = False, **kwargs):

        LigandReceptor.__init__(
            self,
            name = 'Kirouac2010',
            input_method = 'kirouac2010.kirouac2010_interactions',
            ligand_col = 0,
            receptor_col = 1,
            ligand_id_type = 'genesymbol',
            receptor_id_type = 'genesymbol',
            **kwargs
        )


class GuideToPharmacology(LigandReceptor):


    def __init__(self, load_sources = False, **kwargs):

        LigandReceptor.__init__(
            self,
            name = 'Guide2Pharma',
            input_method = 'guide2pharma_interactions',
            ligand_col = 0,
            receptor_col = 2,
            ligand_id_type = 'genesymbol',
            receptor_id_type = 'uniprot',
            **kwargs
        )


    def _default_record_processor(self, record, typ, annot):

        if (
            record.ligand_id_type != 'genesymbol' or
            record.target_id_type != 'uniprot'
        ):

            return

        LigandReceptor._default_record_processor(self, record, typ, annot)


class UniprotLocation(AnnotationBase):

    _eq_fields = ('location',)


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Subcellular localizations from UniProt.
        """

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'UniProt_location',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'uniprot.uniprot_locations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class UniprotFamily(AnnotationBase):

    _eq_fields = ('family', 'subfamily')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Protein families from UniProt.
        """

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'UniProt_family',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'uniprot.uniprot_families',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class UniprotTissue(AnnotationBase):

    _eq_fields = ('tissue', 'level')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Tissue expression levels from UniProt.
        """

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'UniProt_tissue',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'uniprot.uniprot_tissues',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class UniprotTopology(AnnotationBase):

    _eq_fields = ('topology', 'start', 'end')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Topological domains and transmembrane segments from UniProt.
        """

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'UniProt_topology',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'uniprot.uniprot_topology',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class Tcdb(AnnotationBase):

    _eq_fields = ('family', 'tcid')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        Topological domains and transmembrane segments from UniProt.
        """

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'TCDB',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'tcdb.tcdb_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class Mcam(AnnotationBase):

    _eq_fields = ()


    def __init__(self, **kwargs):
        """
        List of cell adhesion molecules (CAMs) from 10.4137/cin.s341.
        """

        AnnotationBase.__init__(
            self,
            name = 'MCAM',
            input_method = 'mcam.mcam_cell_adhesion_molecules',
            **kwargs
        )


class Gpcrdb(AnnotationBase):

    _eq_fields = ('gpcr_class', 'family', 'subfamily')


    def __init__(self, ncbi_tax_id = 9606, **kwargs):
        """
        GPCR classification from GPCRdb - https://gpcrdb.org/.
        """

        if 'organism' not in kwargs:

            kwargs['organism'] = ncbi_tax_id

        AnnotationBase.__init__(
            self,
            name = 'GPCRdb',
            ncbi_tax_id = ncbi_tax_id,
            input_method = 'gpcrdb.gpcrdb_annotations',
            **kwargs
        )


    def _process_method(self):

        #  already the appropriate format, no processing needed
        self.annot = self.data

        delattr(self, 'data')


class AnnotationTable(session_mod.Logger):


    def __init__(
            self,
            proteins = (),
            complexes = (),
            protein_sources = None,
            complex_sources = None,
            use_fields = None,
            ncbi_tax_id = 9606,
            swissprot_only = True,
            use_complexes = True,
            keep_annotators = True,
            create_dataframe = False,
            load = True,
            pickle_file = None,
        ):
        """
        Manages a custom set of annotation resources. Loads data and
        accepts queries, provides methods for converting the data to
        data frame.

        :arg set proteins:
            A reference set of proteins (UniProt IDs).
        :arg set complexes:
            A reference set of complexes.
        :arg set protein_sources:
            Class names providing the protein annotations. If not provided
            the module's ``protein_sources_default`` attribute will be used.
        :arg set complex_sources:
            Class names providing the complex annotations. If not provided
            the module's ``complex_sources_default`` attribute will be used.
        :arg dict use_fields:
            A dict with resource names as keys and tuple of field labels as
            values. If provided for any resource only these fields will be
            used for constructing the data frame. If `None`, the module's
            ``default_fields`` settings will be used.
        :arg bool use_complexes:
            Whether to include complexes in the annotations.
        :arg bool create_dataframe:
            Whether to create a boolean data frame of annotations, apart
            from having the annotator objects.
        :arg bool load:
            Load the data upon initialization. If `False`, you will have a
            chance to call the ``load`` method later.
        """

        session_mod.Logger.__init__(self, name = 'annot')

        self._module = sys.modules[self.__module__]
        self.pickle_file = pickle_file
        self.complexes = complexes
        self.protein_sources = (
            protein_sources
                if protein_sources is not None else
            protein_sources_default
        )
        self.complex_sources = (
            complex_sources
                if complex_sources is not None else
            complex_sources_default
        )
        self.use_fields = use_fields or default_fields
        self.ncbi_tax_id = ncbi_tax_id
        self.keep_annotators = keep_annotators
        self.create_dataframe = create_dataframe
        self.proteins = proteins
        self.swissprot_only = swissprot_only
        self.use_complexes = use_complexes
        self.set_reference_set()
        self.annots = {}

        if load:

            self.load()


    def reload(self):
        """
        Reloads the object from the module level.
        """

        modname = self.__class__.__module__
        mod = __import__(modname, fromlist = [modname.split('.')[0]])
        imp.reload(mod)
        new = getattr(mod, self.__class__.__name__)
        setattr(self, '__class__', new)


    def load(self):

        if self.pickle_file:

            self.load_from_pickle(pickle_file = self.pickle_file)
            return

        self.set_reference_set()
        self.load_protein_resources()
        self.load_complex_resources()

        if self.create_dataframe:

            self.make_dataframe()


    def load_from_pickle(self, pickle_file):

        self._log('Loading from pickle `%s`.' % pickle_file)

        with open(pickle_file, 'rb') as fp:

            self.proteins, self.complexes, self.reference_set, annots = (
                pickle.load(fp)
            )

            self.annots = {}

            for name, (cls_name, data, record_cls) in iteritems(annots):

                if record_cls is not None:

                    modname = record_cls['module']

                    if modname not in sys.modules:

                        mod = __import__(
                            modname,
                            fromlist = [modname.split('.')[0]],
                        )

                    setattr(
                        sys.modules[modname],
                        record_cls['name'],
                        collections.namedtuple(
                            record_cls['name'],
                            record_cls['fields'],
                        ),
                    )

                    record_cls_new = getattr(
                        sys.modules[modname],
                        record_cls['name'],
                    )

                    data = dict(
                        (
                            key,
                            set(
                                record_cls_new(*this_annot)
                                for this_annot in these_annots
                            )
                        )
                        for key, these_annots in iteritems(data)
                    )

                cls = globals()[cls_name]

                self.annots[name] = cls(dump = data)

        self._log('Loaded from pickle `%s`.' % pickle_file)


    def save_to_pickle(self, pickle_file):

        def get_record_class(annot):

            for val in annot.values():

                for elem in val:

                    return elem.__class__


        self._log('Saving to pickle `%s`.' % pickle_file)

        for annot in self.annots.values():

            annot._update_complex_attribute_classes()

        with open(pickle_file, 'wb') as fp:

            classes = dict(
                (
                    name,
                    get_record_class(annot.annot)
                )
                for name, annot in iteritems(self.annots)
            )

            annots = dict(
                (
                    name,
                    (
                        annot.__class__.__name__,
                        dict(
                            (
                                key,
                                set(
                                    tuple(this_annot)
                                    for this_annot in these_annots
                                )
                            )
                            for key, these_annots in iteritems(annot.annot)
                        ),
                        {
                            'name': classes[name].__name__,
                            'module': classes[name].__module__,
                            'fields': classes[name]._fields,
                        }
                        if classes[name] else None
                    )
                )
                for name, annot in iteritems(self.annots)
            )

            pickle.dump(
                obj = (
                    self.proteins,
                    self.complexes,
                    self.reference_set,
                    annots,
                ),
                file = fp,
            )

        self._log('Saved to pickle `%s`.' % pickle_file)


    def set_reference_set(self):

        self.proteins, self.complexes, self.reference_set = (
            AnnotationBase.get_reference_set(
                proteins = self.proteins,
                complexes = self.complexes,
                use_complexes = self.use_complexes,
                ncbi_tax_id = self.ncbi_tax_id,
                swissprot_only = self.swissprot_only,
            )
        )

        self.rows = dict(
            reversed(i)
            for i in enumerate(self.reference_set)
        )


    def load_protein_resources(self):

        self._load_resources(self.protein_sources, self.proteins)


    def load_complex_resources(self):

        self._load_resources(self.complex_sources, self.complexes)


    def _load_resources(self, definitions, reference_set):

        for cls in definitions:

            cls = cls if callable(cls) else getattr(self._module, cls)

            try:

                annot = cls(
                    ncbi_tax_id = self.ncbi_tax_id,
                    reference_set = reference_set,
                )

                self.annots[annot.name] = annot

            except Exception:

                self._log(
                    'Failed to load annotations from resource `%s`.\n'
                    '%s\n' % (
                        cls.__name__
                            if hasattr(cls, '__name__') else
                        str(cls),
                        traceback.format_exc(),
                    )
                )


    def make_dataframe(self, reference_set = None):

        if self.create_dataframe:

            self.df = self.to_dataframe(reference_set = reference_set)


    def ensure_array(self, reference_set = None, rebuild = False):

        if not hasattr(self, 'data') or rebuild:

            self.make_array(reference_set = reference_set)


    def to_array(self, reference_set = None):

        reference_set = reference_set or self.reference_set

        names  = []
        arrays = []

        for resource in self.annots.values():

            # skipping HPA for now because too large number of
            # annotations, it would take very long:
            if resource.name == 'HPA':

                continue

            use_fields = (
                self.use_fields[resource.name]
                    if resource.name in self.use_fields else
                None
            )

            this_names, this_array = resource.to_array(
                    reference_set = reference_set,
                    use_fields = (
                        self.use_fields[resource.name]
                            if resource.name in self.use_fields else
                        None
                    ),
                )

            names.extend(this_names)
            arrays.append(this_array)

        names = np.array(list(itertools.chain(names)))
        data = np.hstack(arrays)

        return names, data


    def make_array(self, reference_set = None):

        self.names, self.data = self.to_array(reference_set = reference_set)
        self.set_cols()


    def set_cols(self):

        self.cols = dict((name, i) for i, name in enumerate(self.names))


    def keep(self, keep):

        ikeep = np.array([
            i for i, name in enumerate(self.names) if name in keep
        ])

        self.names = self.names[ikeep]
        self.data  = self.data[:, ikeep]
        self.set_cols()


    def make_sets(self):

        self.ensure_array()

        self.sets = dict(
            (
                name,
                set(self.reference_set[self.data[:, i]])
            )
            for i, name in enumerate(self.names)
        )


    def annotate_network(self, pa):

        nodes = pa.graph.vs['name']
        edges = [
            (
                nodes[e.source],
                nodes[e.target]
            )
            for e in pa.graph.es
        ]

        nodeannot = []
        edgeannot = []

        for i, uniprot in enumerate(nodes):

            for name, uniprots in iteritems(self.sets):

                if uniprot in uniprots:

                    nodeannot.append((name, i))

        for i, (uniprot1, uniprot2) in enumerate(edges):

            for name1, uniprots1 in iteritems(self.sets):

                for name2, uniprots2 in iteritems(self.sets):

                    if uniprot1 in uniprots1 and uniprot2 in uniprots2:

                        edgeannot.append((name1, name2, i))

        return nodeannot, edgeannot


    def network_stats(self, pa):

        nodeannot, edgeannot = self.annotate_network(pa)

        nodestats = collections.Counter('__'.join(n[0]) for n in nodeannot)

        edgestats = collections.Counter(
            tuple(sorted(('__'.join(e[0]), '__'.join(e[1]))))
            for e in edgeannot
        )

        return nodestats, edgestats


    def export_network_stats(self, pa):

        nodestats, edgestats = self.network_stats(pa)

        with open('annot_edgestats2.tsv', 'w') as fp:

            _ = fp.write('\t'.join(('name1', 'name2', 'count')))
            _ = fp.write('\n')

            _ = fp.write('\n'.join(
                '%s\t%s\t%u' % (name1, name2, cnt)
                for (name1, name2), cnt in iteritems(edgestats)
            ))

        with open('annot_nodestats2.tsv', 'w') as fp:

            _ = fp.write('\t'.join(('name', 'count')))
            _ = fp.write('\n')

            _ = fp.write('\n'.join(
                '%s\t%u' % (name, cnt)
                for name, cnt in iteritems(nodestats)
            ))


    def to_dataframe(self, reference_set = None):

        self._log('Creating data frame from AnnotationTable.')

        self.ensure_array(
            reference_set = reference_set,
            rebuild = reference_set is not None,
        )

        colnames = ['__'.join(name) for name in self.names]

        df = pd.DataFrame(
            data = self.data,
            index = self.reference_set,
            columns = colnames,
        )

        self._log(
            'Created annotation data frame, memory usage: %s.' % (
                common.df_memory_usage(self.df)
            )
        )

        return df


    def make_narrow_df(self):

        self._log('Creating narrow data frame from AnnotationTable.')

        for annot in self.annots.values():

            annot.make_df()

        self.narrow_df = pd.concat(
            annot.df for annot in self.annots.values()
        ).astype(AnnotationBase._dtypes)

        self._log(
            'Created annotation data frame, memory usage: %s.' % (
                common.df_memory_usage(self.narrow_df)
            )
        )


    def search(self, protein):
        """
        Returns a dictionary with all annotations of a protein. Keys are the
        resource names.
        """

        return dict(
            (
                resource,
                annot.annot[protein]
            )
            for resource, annot in iteritems(self.annots)
            if protein in annot.annot
        )


    def all_annotations(self, entity):
        """
        Returns all annotation records for one protein in a single list.
        """

        return [
            aa
            for a in self.annots.values()
            if entity in a.annot
            for aa in a.annot[entity]
        ]


    def all_annotations_str(self, protein):
        """
        Returns all annotation records for one protein serialized.
        """

        return '; '.join(
            str(a) for a in
            self.all_annotations(protein = protein)
        )


    def update_summaries(self):

        self.summaries = dict(
            (
                name,
                a.summary
            )
            for name, a in iteritems(self.annots)
        )


    def summaries_tab(self, outfile = None, return_table = False):

        columns = (
            ('name', 'Resource'),
            ('n_total', 'Entities'),
            ('n_records_total', 'Records'),
            ('records_per_entity', 'Records per entity'),
            ('n_proteins', 'Proteins'),
            ('pct_proteins', 'Proteins [%]'),
            ('n_protein_records', 'Protein records'),
            ('n_complexes', 'Complexes'),
            ('pct_complexes', 'Complexes [%]'),
            ('n_complex_records', 'Complex records'),
            ('complex_annotations_inferred', 'Inferred complex annotations'),
            ('n_mirnas', 'miRNA'),
            ('pct_mirnas', 'miRNA [%]'),
            ('n_mirna_records', 'miRNA records'),
            ('references', 'References'),
            ('curation_effort', 'Curation effort'),
            ('fields', 'Fields'),
        )

        tab = []
        tab.append([f[1] for f in columns])

        tab.extend([
            [
                str(self.summaries[src][f[0]])
                for f in columns
            ]
            for src in sorted(self.summaries.keys())
        ])

        if outfile:

            with open(outfile, 'w') as fp:

                fp.write('\n'.join('\t'.join(row) for row in tab))

        if return_table:

            return tab


    def get_entities(self, entity_type = None):

        entity_type = common.to_set(entity_type)

        entities = set.union(*(
            set(an.annot.keys())
            for an in self.annots.values()
        ))

        return entity.Entity.filter_entity_type(
            entities,
            entity_type = entity_type,
        )


    def get_proteins(self):

        return self.get_entities(entity_type = 'protein')


    def get_complexes(self):

        return self.get_entities(entity_type = 'complex')


    def get_mirnas(self):

        return self.get_entities(entity_type = 'mirna')


    def numof_entities(self, entity_type = None):

        return len(self.get_entities(entity_type = entity_type))


    def numof_proteins(self):

        return len(self.get_proteins())


    def numof_complexes(self):

        return len(self.get_complexes())


    def numof_mirnas(self):

        return len(self.get_mirnas())


    def numof_records(self, entity_type = None):

        return sum(
            an.numof_records(entity_types = entity_type)
            for an in self.annots.values()
        )


    def numof_resources(self):

        return len(self.annots)


    def __repr__(self):

        return (
            '<Annotation database: %u records about %u '
            'entities from %u resources>' % (
                self.numof_records(),
                self.numof_entities(),
                self.numof_resources(),
            )
        )


    def __getitem__(self, item):

        if isinstance(item, common.simple_types):

            if item in self.annots:

                return self.annots[item]

            elif item in self:

                return self.search(item)

        else:

            return dict(
                (it, self[it])
                for it in item
            )


    def __contains__(self, item):

        return (
            item in self.annots or
            any(item in a for a in self.annots.values())
        )


def init_db(
        keep_annotators = True,
        create_dataframe = False,
        use_complexes = True,
        **kwargs
    ):
    """
    Initializes or reloads the annotation database.
    The database will be assigned to the ``db`` attribute of this module.
    """

    globals()['db'] = AnnotationTable(
        keep_annotators = keep_annotators,
        create_dataframe = create_dataframe,
        use_complexes = use_complexes,
        **kwargs
    )


def get_db(
        keep_annotators = True,
        create_dataframe = False,
        use_complexes = True,
        **kwargs
    ):
    """
    Retrieves the current database instance and initializes it if does
    not exist yet.
    """

    if 'db' not in globals():

        init_db(
            keep_annotators = keep_annotators,
            create_dataframe = create_dataframe,
            use_complexes = use_complexes,
            **kwargs
        )

    return globals()['db']
