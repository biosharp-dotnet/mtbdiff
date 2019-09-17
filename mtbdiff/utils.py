#!/usr/bin/env python
"""
    Implements utilities for mtbdiff
    Created July 2019
    Copyright (C) Damien Farrell

    This program is free software; you can redistribute it and/or
    modify it under the terms of the GNU General Public License
    as published by the Free Software Foundation; either version 3
    of the License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program; if not, write to the Free Software
    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""

import os, sys, io, random, subprocess
import string
import numpy as np
import pandas as pd
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Align import MultipleSeqAlignment
from Bio import AlignIO, SeqIO

module_path = os.path.dirname(os.path.abspath(__file__)) #path to module
datadir = os.path.join(module_path, 'data')
mtb_ref = os.path.join(datadir, 'MTB-H37Rv.fna')
RD_file = os.path.join(datadir,'RD.csv')
RD = pd.read_csv(RD_file,comment='#')

def features_to_dataframe(features, cds=False):
    """Get features from a biopython seq record object into a dataframe
    Args:
        features: bio seqfeatures
       returns: a dataframe with a row for each cds/entry.
      """

    allfeat = []
    for (item, f) in enumerate(features):
        x = f.__dict__
        qual = f.qualifiers
        #print(qual)
        x.update(qual)
        d = {}
        d['start'] = f.location.start
        d['end'] = f.location.end
        d['strand'] = f.location.strand
        for i in qual:
            if i in x:
                if type(x[i]) is list:
                    d[i] = x[i][0]
                else:
                    d[i] = x[i]
        allfeat.append(d)
    cols = list(qual.keys())+['start','end']
    df = pd.DataFrame(allfeat,columns=cols)
    if 'gene' in df.columns:
        df['gene'] = df.gene.fillna(df.locus_tag)
    return df

def gff_to_features(gff_file):
    """Get features from gff file"""

    if not os.path.exists(gff_file):
        return
    from BCBio import GFF
    in_handle = open(gff_file,'r')
    rec = list(GFF.parse(in_handle))[0]
    in_handle.close()
    return rec.features

def gff_to_dataframe(filename):

    feats = gff_to_features(filename)
    return features_to_dataframe(feats)

def run_nucdiff(ref, query, outpath='results'):
    """Run nucfdiff"""

    r = os.path.splitext(os.path.basename(ref))[0]
    q = os.path.splitext(os.path.basename(query))[0]
    out = outpath + f'/{r}_{q}'
    if not os.path.exists(out):
        cmd = f'nucdiff {ref} {query} {out} query'
        print (cmd)
        subprocess.check_output(cmd,shell=True)
    else:
        print ('folder already present')
    return

def read_nucdiff_gff(gff_file):
    """Read nucdiff results gff"""

    def get_descr(x):
        return x.Name+'_'+str(x.start)+':'+str(x.end)

    df = gff_to_dataframe(gff_file)
    df['descr'] = df.apply(get_descr,1)
    df['length'] = df.end - df.start
    #remove zero location
    df = df[df.start>0]
    return df

def get_nucdiff_results(path, names, ref=None):
    """Get results from multiple nucdiff folders."""

    struct = []
    snp = []
    if ref is None:
        ref = 'MTB-H37Rv'

    for n in names:
        df = read_nucdiff_gff(f'{path}/{ref}_{n}/results/query_ref_struct.gff')
        df2 = read_nucdiff_gff(f'{path}/{ref}_{n}/results/query_ref_snps.gff')
        df['label'] = n
        df2['label'] = n
        struct.append(df)
        snp.append(df2)
    drop = ['blk_query','blk_query_len','blk_ref','blk_ref_len','breakpoint_query']
    struct = pd.concat(struct, sort=True)
    struct = struct.drop(columns=drop)
    snp = pd.concat(snp, sort=True)
    return struct, snp

def find_regions(result):
    """find known regions overlap in results from nucdiff"""

    #result = result[result.Name.isin(['insertion','deletion'])]
    RD = pd.read_csv(RD_file,comment='#')
    regions = ['RD'+str(i) for i in range(1,15)]
    RD = RD[RD.RD_name.isin(regions)]
    found=[]
    for i,r in list(result.iterrows()):
        #df = RD[ (abs(RD.Start-r.start)<800) | (abs(RD.Stop-r.end)<800)].copy()
        df = RD[((r.start>RD.Start) & (r.start<RD.Stop)) |
                  ((r.end>RD.Start) & (r.end<RD.Stop)) |
                  ((r.start<RD.Start) & (r.end>RD.Stop))].copy()
        if len(df)>0:
            idcol = r.keys()[0]
            df['name'] = r[idcol]
            df['label'] = r.label
            df['start'] = r.start
            found.append(df)
    found = pd.concat(found)
    return found

def get_region(x, stcoord='start', endcoord='end'):
    """Get an overlapping RD from coord"""

    st = x[stcoord]; end = x[endcoord]
    found = RD[ (st>RD.Start) & (st<RD.Stop) |
                 ((end>RD.Start) & (end<RD.Stop)) |
                 ((st<RD.Start) & (end>RD.Stop))]
    if len(found)>0:
        return found.iloc[0].RD_name

def get_mtb_gff():
    gff_file = analysis.mtb_gff
    feat = utils.gff_to_dataframe(gff_file)
    feat = feat[feat.gbkey=='Gene']
    return feat

def sites_matrix(struct, columns=['label'],index=['start','end'], freq=0):
    """Pivot by start site"""

    X = pd.pivot_table(struct,index=index,columns=columns,values='Name',aggfunc='first')
    X[X.notnull()] = 1
    X = X.fillna(0)
    #remove unique?
    X = X[X.sum(1)>freq]
    return X

def RD_matrix(struct, columns=['label']):
    """pivot by presence of RDs"""

    X = pd.pivot_table(struct,index=['RD'],columns=columns,values='Name',aggfunc='count')
    X[X.notnull()] = 1
    X = X.fillna(0)
    return X


def get_assembly_summary(id):

    from Bio import Entrez
    esummary_handle = Entrez.esummary(db="assembly", id=id, report="full")
    esummary_record = Entrez.read(esummary_handle)
    return esummary_record

def get_assemblies(term, download=True, path='assemblies'):
    """Download genbank assemblies for a given search term.
    Args:
        term: usually organaism name"""

    from Bio import Entrez
    Entrez.email = "A.N.Other@example.com"
    handle = Entrez.esearch(db="assembly", term=term, retmax='200')
    record = Entrez.read(handle)
    ids = record['IdList']
    print (f'found {len(ids)} ids')
    links = []
    for id in ids:
        #get summary
        summary = get_assembly_summary(id)
        #get ftp link
        url = summary['DocumentSummarySet']['DocumentSummary'][0]['FtpPath_RefSeq']
        if url == '':
            continue
        label = os.path.basename(url)
        link = os.path.join(url,label+'_genomic.fna.gz')
        print (link)
        links.append(link)
        if download == True:
            #download link
            urllib.request.urlretrieve(link, f'{label}.fna.gz')
    return links
