#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  This file is part of the `pypath` python module
#
#  Copyright
#  2014-2021
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

import os
import re
import collections
import itertools

try:
    import cPickle as pickle
except:
    import pickle

import bs4

import pypath.share.curl as curl
import pypath.share.common as common
import pypath.share.progress as progress
import pypath.share.settings as settings
import pypath.share.session as session_mod
import pypath.resources.urls as urls
import pypath.internals.intera as intera

_logger = session_mod.Logger(name = 'hpmr_input')
_log = _logger._log


def get_hpmr(use_cache = None):
    """
    Downloads ligand-receptor and receptor-receptor interactions from the
    Human Plasma Membrane Receptome database.
    """

    def get_complex(interactors, typ, recname = None, references = None):
        """
        typ : str
            `Receptor` or `Ligand`.
        """

        components = [i[1] for i in interactors if i[0] == typ]

        if typ == 'Receptor' and recname:
            components.append(recname)

        if len(components) == 1:
            return components[0]

        elif len(components) > 1:
            return components


    cachefile = settings.get('hpmr_preprocessed')
    use_cache = (
        use_cache
            if isinstance(use_cache, bool) else
        settings.get('use_intermediate_cache')
    )

    if os.path.exists(cachefile) and use_cache:
        _log('Reading HPMR data from cache file `%s`.' % cachefile)

        return pickle.load(open(cachefile, 'rb'))

    rerecname = re.compile(r'Receptor ([A-z0-9]+) interacts with:')
    reint = re.compile(r'(Receptor|Ligand) ([A-z0-9]+) -')
    rerefid = re.compile(r'list_uids=([- \.:,0-9A-z]+)')
    refamid = re.compile(r'.*FamId=([0-9\.]+)')

    a_family_title = 'Open Family Page'
    a_receptor_title = 'Open Receptor Page'
    a_titles = {a_family_title, a_receptor_title}

    interactions = []
    complex_interactions = []
    families = {}
    recpages = []

    c = curl.Curl(urls.urls['hpmri']['browse'])
    soup = bs4.BeautifulSoup(c.result, 'html.parser')

    this_family = ('0', None)
    this_subfamily = ('0', None)
    this_subsubfamily = ('0', None)

    for a in soup.find_all('a'):
        a_title = a.attrs['title'] if 'title' in a.attrs else None

        if a_title not in a_titles:
            continue

        if a_title == a_family_title:
            family_id = refamid.match(a.attrs['href']).groups()[0]

            if family_id.startswith(this_subfamily[0]):
                this_subsubfamily = (family_id, a.text)

            elif family_id.startswith(this_family[0]):
                this_subfamily = (family_id, a.text)
                this_subsubfamily = ('0', None)

            else:
                this_family = (family_id, a.text)
                this_subfamily = ('0', None)
                this_subsubfamily = ('0', None)

        elif a_title == a_receptor_title:
            recpages.append((
                a.attrs['href'],
                this_family[1],
                this_subfamily[1],
                this_subsubfamily[1],
            ))

    prg = progress.Progress(len(recpages), 'Downloading HPMR data', 1)

    i_complex = 0

    for url, family, subfamily, subsubfamily in recpages:
        prg.step()

        c = curl.Curl(url)

        if c.result is None:
            #print('No receptor page: %s' % url)
            continue

        soup = bs4.BeautifulSoup(c.result, 'html.parser')
        ints = soup.find('div', {'id': 'GeneInts'})

        if not ints:
            #print('No interactions: %s' % url)
            continue

        recname = rerecname.search(
            ints.find_previous_sibling('span').text
        )
        recname = recname.groups()[0] if recname else 'Unknown'

        if recname == 'Unknown':
            # print('Could not find receptor name: %s' % url)
            continue

        recname_u = mapping.map_name0(recname, 'genesymbol', 'uniprot')

        if not recname_u:
            continue

        families[recname_u] = (
            family,
            subfamily,
            subsubfamily,
        )

        for td in ints.find_all('td'):
            interactors = []

            for span in td.find_all('span', {'class': 'IntRow'}):
                ints = reint.search(span.text)

                if ints:
                    interactors.append(ints.groups())

            references = []

            for ref in td.find_all(
                'a', {'title': 'click to open reference in new window'}):

                references.append(
                    rerefid.search(ref.attrs['href']).groups()[0].strip()
                )

            interactors_u = []

            for role, genesymbol in interactors:
                uniprot = (
                    mapping.map_name0(genesymbol, 'genesymbol', 'uniprot')
                )

                if uniprot:
                    interactors_u.append((role, uniprot))

            interactions.extend([
                [recname_u, i[0], i[1], ';'.join(references)]
                for i in interactors_u
            ])

            rec_complex = get_complex(
                interactors_u,
                'Receptor',
                recname = recname_u,
                references = references,
            )
            lig_complex = get_complex(
                interactors_u,
                'Ligand',
                references = references,
            )

            if (
                isinstance(rec_complex, list) or
                isinstance(lig_complex, list)
            ):
                complex_interactions.append((lig_complex, rec_complex))

    prg.terminate()

    result = {
        'interactions': interactions,
        'families': families,
        'complex_interactions': complex_interactions,
    }

    pickle.dump(result, open(cachefile, 'wb'))

    return result


def hpmr_complexes(use_cache = None):

    hpmr_data = get_hpmr(use_cache = use_cache)

    complexes = {}

    i_complex = 0

    for components in itertools.chain(*hpmr_data['complex_interactions']):
        if isinstance(components, list):
            cplex = intera.Complex(
                components = components,
                sources = 'HPMR',
                ids = 'HPMR-COMPLEX-%u' % i_complex,
            )

            complexes[cplex.__str__()] = cplex

    return complexes


def hpmr_interactions(use_cache = None):

    hpmr_data = get_hpmr(use_cache = use_cache)

    return hpmr_data['interactions']


def hpmr_annotations(use_cache = None):

    annot = collections.defaultdict(set)

    HPMRAnnotation = collections.namedtuple(
        'HPMRAnnotation',
        ('role', 'mainclass', 'subclass', 'subsubclass'),
    )

    hpmr_data = get_hpmr(use_cache = use_cache)

    for i in hpmr_data['interactions']:
        # first partner is always a receptor
        # (because ligand pages simply don't work on HPMR webpage)
        args1 = ('Receptor',) + (
            hpmr_data['families'][i[0]]
                if i[0] in hpmr_data['families'] else
            (None, None, None)
        )
        # the second is either a ligand or another receptor
        args2 = (i[1],) + (
            hpmr_data['families'][i[2]]
                if i[2] in hpmr_data['families'] else
            (None, None, None)
        )

        annot[i[0]].add(HPMRAnnotation(*args1))
        annot[i[2]].add(HPMRAnnotation(*args2))

    for uniprot, classes in iteritems(hpmr_data['families']):
        args = ('Receptor',) + classes

        annot[uniprot].add(HPMRAnnotation(*args))

    return dict(annot)
