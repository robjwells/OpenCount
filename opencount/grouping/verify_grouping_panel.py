import os, sys, traceback, pdb, csv, re
try:
    import cPickle as pickle
except:
    import pickle

from os.path import join as pathjoin

import wx
from wx.lib.scrolledpanel import ScrolledPanel

import common
from verify_overlays_new import VerifyOverlays
import digit_group_new
sys.path.append('..')
import specify_voting_targets.util_gui as util_gui

class VerifyGroupingMainPanel(wx.Panel):
    # Number of exemplars to grab for each group
    NUM_EXMPLS = 5

    def __init__(self, parent, *args, **kwargs):
        wx.Panel.__init__(self, parent, *args, **kwargs)
        
        self.proj = None
        self.stateP = None

        self.imgpath_groups = None
        self.group_exemplars = None
        self.bbs_map = None
        self.rlist_map = None

        # VERIFY_RESULTS: maps {(attrtype,attrval): [imgpath_i, ...]}
        self.verify_results = None

        self.init_ui()

    def init_ui(self):
        self.verify_panel = VerifyOverlays(self)
        
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.verify_panel, proportion=1, flag=wx.EXPAND)
        self.SetSizer(self.sizer)

        self.Layout()

    def start(self, proj, stateP):
        self.proj = proj
        self.proj.addCloseEvent(self.save_session)
        self.stateP = stateP
        
        if not self.restore_session():
            self.imgpath_groups = create_groups(proj)
            self.group_exemplars = get_group_exemplars(proj)
            self.rlist_map = get_rlist_map(proj)

        verifyoverlays_stateP = pathjoin(proj.projdir_path, '_state_verifyoverlays.p')

        self.verify_panel.start(self.imgpath_groups, self.group_exemplars, self.rlist_map, 
                                ondone=self.on_verify_done, do_align=True, stateP=verifyoverlays_stateP)
        self.Layout()

    def stop(self):
        if not self.proj:
            return
        self.save_session()
        self.proj.removeCloseEvent(self.save_session)
        self.verify_panel.stop()
        self.export_results()

    def restore_session(self):
        try:
            state = pickle.load(open(self.stateP, 'rb'))
            self.imgpath_groups = state['imgpath_groups']
            self.group_exemplars = state['group_exemplars']
            self.rlist_map = state['rlist_map']
            self.bbs_map = state['bbs_map']
        except:
            return False
        return True
    def save_session(self):
        state = {'imgpath_groups': self.imgpath_groups,
                 'group_exemplars': self.group_exemplars,
                 'rlist_map': self.rlist_map,
                 'bbs_map': self.bbs_map}
        pickle.dump(state, open(self.stateP, 'wb'), pickle.HIGHEST_PROTOCOL)
        self.verify_panel.save_session()

    def export_results(self):
        """ Establishes the ballot -> group relationship, by exporting
        the BALLOT_TO_GROUP dict:
            {int ballotID: int groupID}
        and GROUP_TO_BALLOTS:
            {int groupID: [int ballotID_i, ...]}
        and GROUP_INFOMAP:
            {int groupID: {str key: val}}
        and GROUP_EXMPLS:
            {int groupID: [int ballotID_i, ...]}
        """
        if not self.verify_results:
            print "...Can't export GroupingPanel results without self.verify_results..."
            return
        b2g = {}
        g2b = {}
        group_infomap = {}
        group_exmpls = {}

        b2imgs = pickle.load(open(self.proj.ballot_to_images, 'rb'))
        img2b = pickle.load(open(self.proj.image_to_ballot, 'rb'))

        partitions_map = pickle.load(open(pathjoin(self.proj.projdir_path,
                                                   self.proj.partitions_map), 'rb'))
        partitions_invmap = pickle.load(open(pathjoin(self.proj.projdir_path,
                                                      self.proj.partitions_invmap), 'rb'))
        attrprops = pickle.load(open(pathjoin(self.proj.projdir_path, 
                                              self.proj.attrprops), 'rb'))

        attrs = pickle.load(open(self.proj.ballot_attributesfile, 'rb'))
        attrmap = {} # maps {str attrtype: dict attr}
        for attr in attrs:
            attrmap['_'.join(sorted(attr['attrs']))] = attr

        # 1.) First, mark each ballot with its attribute properties
        ballot_attrvals = {} # maps {int ballotID: {attrtype: attrval}}

        # Note: If groupingmode was PER_PARTITION, then self.VERIFY_RESULTS
        # will only have information about one ballot from each partition.
        for (attrtype, attrval), imgpaths in self.verify_results.iteritems():
            for imgpath in imgpaths:
                ballotid = img2b[imgpath]
                if attrmap[attrtype]['grp_per_partition']:
                    ballotids = partitions_map[partitions_invmap[ballotid]]
                else:
                    ballotids = [ballotid]
                for ballotid in ballotids:
                    # Don't forget to add in the partition id!
                    partitionID = partitions_invmap[ballotid]
                    ballot_attrvals.setdefault(ballotid, {})[attrtype] = attrval
                    ballot_attrvals[ballotid]['pid'] = partitionID

        # 1.b.) Add CUSTOM_ATTRIBUTE mapping
        ss_dicts = {} # maps {str attrtype: dict ss_dict}
        for attrtype, cattrprops in attrprops['CUSTATTR'].iteritems():
            if cattrprops['type'] == cust_attrs.TYPE_SPREADSHEET:
                ssdict = ss_dicts.get(attrtype, None)
                if ssdict == None:
                    ss_dicts[attrtype] = read_sscustattr(cattrprops['sspath'])
                    ssdict = ss_dicts[attrtype]
                for ballotid, ballotprops in ballot_attrvals.iteritems():
                    inval = ballotprops[cattrprops['attrin']]
                    ballotprops[attrtype] = ssdict[inval]
            elif cattrprops['type'] == cust_attrs.TYPE_FILENAME:
                for ballotid, ballotprops in ballot_attrvals.iteritems():
                    # Arbitrarily select the first image path...good?
                    imgname = b2imgs[ballotid][0]
                    matches = re.search(cattrprops['filename_regex'], imgname)
                    outval = matches.groups()[0]
                    ballotprops[attrtype] = outval

        # 2.) Create each group, based on the unique ballot property values
        group_idx_map = {} # maps {((attrtype,attrval), ...): int groupIdx}
        group_cnt = 0
        for ballotid, ballotprops in ballot_attrvals.iteritems():
            # 2.a.) Filter out any 'is_tabulationonly' attrtypes
            ballotprops_grp = {} # maps {attrtype: attrval}
            for ballotattrtype, ballotattrval in ballotprops.iteritems():
                if ballotattrtype == 'pid':
                    # Always add the partition id
                    ballotprops_grp[ballotattrtype] = ballotattrval
                    continue
                for attrmode, attrdicts in attrprops.iteritems():
                    for attrtype, attrpropdict in attrdicts.iteritems():
                        if attrtype == ballotattrtype and not attrpropdict['is_tabulationonly']:
                            ballotprops_grp[ballotattrtype] = ballotattrval
            ordered_props = tuple(sorted(ballotprops_grp.items(), key=lambda t: t[0]))
            group_idx = group_idx_map.get(ordered_props, None)
            if group_idx == None:
                group_idx = group_cnt
                group_idx_map[ordered_props] = group_idx
                group_cnt += 1
            b2g[ballotid] = group_idx
            g2b.setdefault(group_idx, []).append(ballotid)
            group_infomap[group_idx] = ballotprops

        # 3.) Finally, grab a set of exemplar images from each group
        for groupid, ballotids in g2b.iteritems():
            for i, ballotid in enumerate(ballotids):
                if i >= self.NUM_EXMPLS:
                    break
                group_exmpls.setdefault(groupid, []).append(ballotid)

        # 4.) Also, export to proj.group_results.csv, for integration with
        # quarantine/post-processing panels.
        all_attrtypes = set()
        for attrmode, attrtype_dicts in attrprops.iteritems():
            for attrtype, attrprops in attrtype_dicts.iteritems():
                all_attrtypes.add(attrtype)
        fields = ('ballotid', 'groupid') + tuple(sorted(tuple(all_attrtypes))) + ('pid',)
        csvfile = open(self.proj.grouping_results, 'wb')
        dictwriter = csv.DictWriter(csvfile, fieldnames=fields)
        try:
            dictwriter.writeheader()
        except:
            util_gui._dictwriter_writeheader(csvfile, fields)
        rows = []
        for ballotid, ballotprops in ballot_attrvals.iteritems():
            row = {}
            for attrtype, attrval in ballotprops.iteritems():
                row[attrtype] = attrval
            row['ballotid'] = ballotid
            row['groupid'] = b2g[ballotid]
            rows.append(row)
        dictwriter.writerows(rows)
        csvfile.close()

        pickle.dump(b2g, open(pathjoin(self.proj.projdir_path,
                                       self.proj.ballot_to_group), 'wb'),
                    pickle.HIGHEST_PROTOCOL)
        pickle.dump(g2b, open(pathjoin(self.proj.projdir_path,
                                       self.proj.group_to_ballots), 'wb'),
                    pickle.HIGHEST_PROTOCOL)
        pickle.dump(group_infomap, open(pathjoin(self.proj.projdir_path,
                                                 self.proj.group_infomap), 'wb'),
                    pickle.HIGHEST_PROTOCOL)
        pickle.dump(group_exmpls, open(pathjoin(self.proj.projdir_path,
                                                self.proj.group_exmpls), 'wb'),
                    pickle.HIGHEST_PROTOCOL)
        
    def on_verify_done(self, verify_results):
        """ 
        Input:
            dict VERIFY_RESULTS: maps {(attrtype,attrval): [imgpath_i, ...]}
        """
        print "...Verify Done!..."
        attrs = pickle.load(open(self.proj.ballot_attributesfile, 'rb'))
        if exists_imgattr(self.proj):
            # Convert the attrpatchpaths in VERIFY_RESULTS back into 
            # voted imgpaths, using imgpatch2imgpath
            imgpatch2imgpath = pickle.load(open(pathjoin(self.proj.projdir_path,
                                                         self.proj.imgpatch2imgpath), 'rb'))
            verify_results = apply_patch2imgpath_fix(verify_results, attrs, imgpatch2imgpath)

        if exists_digattr(self.proj):
            # Munge the single-digit groups in GROUP_RESULTS into the normal
            # digitattr groups.
            digpatch2imgpath = pickle.load(open(pathjoin(self.proj.projdir_path,
                                                         self.proj.digpatch2imgpath), 'rb'))
            verify_results = apply_singledigit_fix(verify_results, attrs, digpatch2imgpath)
        self.verify_results = verify_results

def exists_imgattr(proj):
    attrs = pickle.load(open(proj.ballot_attributesfile, 'rb'))
    for attr in attrs:
        if not attr['is_digitbased']:
            return True
    return False
def exists_digattr(proj):
    attrs = pickle.load(open(proj.ballot_attributesfile, 'rb'))
    for attr in attrs:
        if attr['is_digitbased']:
            return True
    return False

def create_groups(proj):
    """
    Input:
        obj PROJ:
    Output:
        dict IMGPATH_GROUPS. IMGPATH_GROUPS maps
            {(attrtype,attrval): [imgpath_i, ...]}
    """
    extract_results = pickle.load(open(pathjoin(proj.projdir_path,
                                                proj.extract_results), 'rb'))
    digitgroup_results = pickle.load(open(pathjoin(proj.projdir_path,
                                                   proj.digitgroup_results), 'rb'))
    b2imgs = pickle.load(open(proj.ballot_to_images, 'rb'))
    img2page = pickle.load(open(pathjoin(proj.projdir_path,
                                         proj.image_to_page), 'rb'))
    attrs = pickle.load(open(proj.ballot_attributesfile, 'rb'))
    imgpath_groups0 = create_imgbased_groups(extract_results, attrs,
                                             b2imgs, img2page, proj)
    imgpath_groups1 = create_digitbased_groups(digitgroup_results, 
                                               attrs, b2imgs, img2page, proj)
    return dict(imgpath_groups0.items() + imgpath_groups1.items())

def create_imgbased_groups(extract_results, attrs, b2imgs, img2page, proj):
    """
    Input:
        dict EXTRACT_RESULTS: maps {int ballotID: {attrtype: {'attrOrder': attrorder, 'err': err,
                                                              'exemplar_idx': exemplar_idx,
                                                              'patchpath': patchpath}}}
        dict MULTEXEMPLARS_MAP: maps {attrtype: {attrval: [(subpatchP, blankP, (x1,y1,x2,y2)), ...]}}
        list ATTRS: [dict attr_i, ...]
    Output:
        dict IMGPATH_GROUPS. IMGPATH_GROUPS maps
            {(attrtype, attrval): [imgpath_i, ...]}.
    """
    if not extract_results:
        return {}
    multexemplars_map = pickle.load(open(pathjoin(proj.projdir_path,
                                                  proj.multexemplars_map), 'rb'))
    groups = {}
    # Prepopulate GROUPS with all possible attrtype->attrval combinations.
    for attrtype, stuffdict in multexemplars_map.iteritems():
        for attrval in stuffdict:
            groups[(attrtype, attrval)] = []
    for ballotid, attrtypedicts in extract_results.iteritems():
        for attrtype, attrdict in attrtypedicts.iteritems():
            attrOrder = attrdict['attrOrder']
            patchpath = attrdict['patchpath']
            attrval = attrOrder[0]
            groups.setdefault((attrtype, attrval), []).append(patchpath)
    return groups

def create_digitbased_groups(digitgroup_results, attrs, b2imgs, img2page, proj):
    """
    Input:
        dict DIGITGROUP_RESULTS: maps {str digattrtype: {int ID: [str digitstr, imgpath, [str digit_i,(x1,y1,x2,y2),score_i,digpatchpath],...]}}.
            If GROUP_MODE is by partition, then ID is partitionID. If GROUP_MODE
            is by ballot, then ID is ballotID.
        dict DIGMULTEXEMPLARS_MAP: maps {str digit: [(regionP, (x1,y1,x2,y2), exmplrP), ...]}
        list ATTRS: [dict attr_i, ...]
    Output:
        dict IMGPATH_GROUPS. IMGPATH_GROUPS maps
            {(attrtype, attrval): [imgpath_i, ...]}.
            particular, this splits up by digit.
    """
    def get_side(attrs, attrtype):
        for attr in attrs:
            attrtypestr = '_'.join(sorted(attr['attrs']))
            if attrtypestr == attrtype:
                return attr['side']
        print "Badness -- couldn't find attribute {0}.".format(attrtype)
        pdb.set_trace()
        return None
    if not digitgroup_results:
        return {}
    digmultexemplars_map = pickle.load(open(pathjoin(proj.projdir_path,
                                                     proj.digitmultexemplars_map), 'rb'))
    imgpath_groups = {} # maps {(attrtype,digit): [imgpath_i, ...]}
    for attrtype, info in digitgroup_results.iteritems():
        # Prepopulate IMGPATH_GROUPS with every attrtype->digit combination
        for digitval in digmultexemplars_map:
            imgpath_groups[(attrtype, digitval)] = []
        page = get_side(attrs, attrtype)
        for ID, digitmats in info.iteritems():
            digitstr, imgpath, digitinfo = digitmats
            for idx, (digit, (x1,y1,x2,y2), score, digpatchpath) in enumerate(digitinfo):
                imgpath_groups.setdefault((attrtype, digit), []).append(digpatchpath)
    return imgpath_groups

def get_group_exemplars(proj):
    """ For each grouplabel L, return an exemplar imgpath that visually
    represents L.
    Input:
        obj PROJ:
    Output:
        dict GROUP_EXEMPLARS. maps {(attrtype, attrval): [imgpath_i, ...]}
    """
    digit_exemplars = get_digit_exemplars(proj)
    img_exemplars = get_img_exemplars(proj)
    return dict(digit_exemplars.items() + img_exemplars.items())

def get_img_exemplars(proj):
    # MULTEXEMPLARS_MAP: maps {attrtype: {attrval: [(subpatchP, blankpath, (x1,y1,x2,y2)), ...]}}
    multexemplars_map = pickle.load(open(pathjoin(proj.projdir_path,
                                                  proj.multexemplars_map), 'rb'))
    exemplars = {} 
    for attrtype, attrdict in multexemplars_map.iteritems():
        for attrval, tuples in attrdict.iteritems():
            for (subpatchP, blankpath, (x1,y1,x2,y2)) in tuples:
                exemplars.setdefault((attrtype,attrval), []).append(subpatchP)
    return exemplars

def get_digit_exemplars(proj):
    attrs = pickle.load(open(proj.ballot_attributesfile, 'rb'))
    digattrtype = None
    for attr in attrs:
        if attr['is_digitbased']:
            digattrtype = '_'.join(sorted(attr['attrs']))
            break
    if digattrtype == None:
        # Means there are no digit attributes in this election
        return {}
    # dict DIGIT_EXEMPLARS: maps {str digit: [(regionpath_i, (x1,y1,x2,y2), exemplarpath_i), ...]}
    if os.path.exists(pathjoin(proj.projdir_path, proj.digitmultexemplars_map)):
        digit_exemplars = pickle.load(open(pathjoin(proj.projdir_path, proj.digitmultexemplars_map), 'rb'))
    else:
        digit_exemplars = digit_group_new.compute_digit_exemplars(proj)
    group_exemplars = {}
    for digit, exemplars_info in digit_exemplars.iteritems():
        tag = (digattrtype, digit)
        exemplar_imgpaths = []
        for (regionpath, (x1,y1,x2,y2), exemplarpath) in exemplars_info:
            exemplar_imgpaths.append(exemplarpath)
        group_exemplars[tag] = exemplar_imgpaths
    return group_exemplars

def get_rlist_map(proj):
    """
    Input:
        obj PROJ:
    Output:
        dict RLIST_MAP. maps {str imgpath: (groupID_0, ...)}
    """
    return {}

def apply_patch2imgpath_fix(verify_results, attrs, imgpatch2imgpath):
    """ Converts patchpaths to ballotids, for img-based attributes.  """
    def is_imgbased(attrs, attrtype):
        for attr in attrs:
            attrtypestr = '_'.join(sorted(attr['attrs']))
            if attrtypestr == attrtype:
                return not attr['is_digitbased']
        print "Uh oh, couldn't find attrtype {0}.".format(attrtype)
        pdb.set_trace()
    out = {}
    for (attrtype, attrval), patchpaths in verify_results.iteritems():
        if not is_imgbased(attrs, attrtype):
            out[(attrtype, attrval)] = patchpaths
        else:
            imgpaths = [imgpatch2imgpath[patchpath] for patchpath in patchpaths]
            out[(attrtype, attrval)] = imgpaths
    return out

def apply_singledigit_fix(verify_results, attrs, digpatch2imgpath):
    """ Converts the individual digit 'attributes' back into the original
    digit-based attribute.
    Input:
        dict VERIFY_RESULTS: maps {(attrtype, attrval): [imgpath_i, ...]}
        list ATTRS: list of attr dicts, [dict attr_i, ...]
        dict DIGPATCH2IMGPATH: maps {digpatchpatch: (str imgpath, int idx)}
    Output:
        dict VERIFY_RESULTS_FIX: maps {(attrtype,attrval): [imgpath_i, ...]}
    """
    digitattrtype = None
    for attr in attrs:
        if attr['is_digitbased']:
            digitattrtype = '_'.join(sorted(attr['attrs']))
            break
    assert digitattrtype != None
    
    d_map = {} # maps {imgpath: {int idx: str digit}}
    verify_results_fixed = {}

    for (attrtype, attrval), digpatchpaths in verify_results.iteritems():
        if attrtype == digitattrtype:
            for digpatchpath in digpatchpaths:
                imgpath, idx = digpatch2imgpath[digpatchpath]
                d_map.setdefault(imgpath, {})[idx] = attrval
        else:
            verify_results_fixed[(attrtype, attrval)] = digpatchpaths
            
    for imgpath, digitidx_map in d_map.iteritems():
        digits_lst = []
        for i, idx in enumerate(sorted(digitidx_map.keys())):
            assert i == idx
            digits_lst.append(digitidx_map[idx])
        digitstrval = ''.join(digits_lst)
        print "For imgP {0}, digitval is: {1}".format(imgpath, digitstrval)
        verify_results_fixed.setdefault((digitattrtype, digitstrval), []).append(imgpath)
    return verify_results_fixed

def read_sscustattr(sspath):
    """ Reads in the SSPATH csv file, and returns it as a dictionary for
    more efficient retrievals.
    """
    reader = csv.DictReader(open(sspath, 'rb'))
    outdict = {} # maps {str in: str out}
    for row in reader:
        outdict[row['in']] = row['out']
    return outdict