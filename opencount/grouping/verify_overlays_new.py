import os, sys, pdb, traceback, time
try:
    import cPickle as pickle
except:
    import pickle

import wx
from wx.lib.scrolledpanel import ScrolledPanel
from wx.lib.pubsub import Publisher

import cv, numpy as np, scipy, scipy.misc, Image
import make_overlays
import util
import cluster_imgs

class VerifyOverlaysMainPanel(wx.Panel):
    def __init__(self, parent, *args, **kwargs):
        wx.Panel.__init__(self, parent, *args, **kwargs)

        self.proj = None
        self.stateP = None

    def start(self, proj, stateP):
        self.proj = proj
        self.stateP = stateP

        self.verifyoverlays.start()

    def stop(self):
        self.export_results()

    def export_results(self):
        pass

class ViewOverlays(ScrolledPanel):
    def __init__(self, parent, *args, **kwargs):
        ScrolledPanel.__init__(self, parent, *args, **kwargs)

        # list GROUPS: [obj GROUP_i, ...]
        self.groups = None

        # dict GROUPID2TAG: maps {int groupid: str tag}
        self.groupid2tag = None 
        # dict TAG2GROUPID: maps {str tag: int groupid}
        self.tag2groupid = None

        # dict BBS_MAP: maps {(tag, str imgpath): (x1,y1,x2,y2)}
        self.bbs_map = None
        
        # IDX: Current idx into self.GROUPS that we are displaying
        self.idx = None

        self.init_ui()

    def overlays_layout_vert(self):
        """ Layout the overlay patches s.t. there is one row of N columns. 
        Typically called when the patch height > patch width.
        """
        self.sizer_overlays.SetOrientation(wx.VERTICAL)
        self.sizer_overlays_voted.SetOrientation(wx.HORIZONTAL)
        self.sizer_min.SetOrientation(wx.VERTICAL)
        self.sizer_max.SetOrientation(wx.VERTICAL)
        self.sizer_attrpatch.SetOrientation(wx.VERTICAL)
        self.sizer_diff.SetOrientation(wx.VERTICAL)
    def overlays_layout_horiz(self):
        """ Layout the overlay patches s.t. there are N rows of 1 column.
        Typically called when the patch width > patch height.
        """
        self.sizer_overlays.SetOrientation(wx.HORIZONTAL)
        self.sizer_overlays_voted.SetOrientation(wx.VERTICAL)
        self.sizer_min.SetOrientation(wx.HORIZONTAL)
        self.sizer_max.SetOrientation(wx.HORIZONTAL)
        self.sizer_attrpatch.SetOrientation(wx.HORIZONTAL)
        self.sizer_diff.SetOrientation(wx.HORIZONTAL)
    def set_patch_layout(self, orient='horizontal'):
        """ Change the orientation of the overlay patch images. Either
        arrange 'horizontal', or stack 'vertical'.
        """
        if orient == 'horizontal':
            sizer = self.overlays_layout_horiz()
        else:
            sizer = self.overlays_layout_vert()
        self.Layout()
        self.Refresh()

    def init_ui(self):
        txt_0 = wx.StaticText(self, label="Number of images in group: ")
        self.txtctrl_num_elements = wx.TextCtrl(self, value='0')
        self.listbox_groups = wx.ListBox(self, size=(200, 300))
        self.listbox_groups.Bind(wx.EVT_LISTBOX, self.onListBox_groups)
        sizer_numimgs = wx.BoxSizer(wx.HORIZONTAL)
        sizer_numimgs.AddMany([(txt_0,), (self.txtctrl_num_elements,)])
        sizer_groups = wx.BoxSizer(wx.VERTICAL)
        sizer_groups.AddMany([(sizer_numimgs,), (self.listbox_groups,)])

        st1 = wx.StaticText(self, -1, "min: ")
        st2 = wx.StaticText(self, -1, "max: ")
        st3 = wx.StaticText(self, -1, "Looks like? ")
        st4 = wx.StaticText(self, -1, "diff: ")
        self.st1, self.st2, self.st3, self.st4 = st1, st2, st3, st4

        self.minOverlayImg = wx.StaticBitmap(self, bitmap=wx.EmptyBitmap(1, 1))
        self.maxOverlayImg = wx.StaticBitmap(self, bitmap=wx.EmptyBitmap(1, 1))
        self.txt_exemplarTag = wx.StaticText(self, label='')
        self.exemplarImg = wx.StaticBitmap(self, bitmap=wx.EmptyBitmap(1, 1))
        self.diffImg = wx.StaticBitmap(self, bitmap=wx.EmptyBitmap(1, 1))

        maxTxtW = max([txt.GetSize()[0] for txt in (st1, st2, st3, st4)]) + 20

        sizer_overlays = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_overlays = sizer_overlays
        self.sizer_overlays_voted = wx.BoxSizer(wx.VERTICAL)
        self.sizer_min = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_min.AddMany([(st1,), ((maxTxtW-st1.GetSize()[0],0),), (self.minOverlayImg,)])
        self.sizer_max = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_max.AddMany([(st2,), ((maxTxtW-st2.GetSize()[0],0),), (self.maxOverlayImg,)])
        self.sizer_innerattrpatch = wx.BoxSizer(wx.VERTICAL)
        self.sizer_innerattrpatch.AddMany([(self.txt_exemplarTag,), (self.exemplarImg,)])
        self.sizer_attrpatch = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_attrpatch.AddMany([(st3,), ((maxTxtW-st3.GetSize()[0],0),), (self.sizer_innerattrpatch,)])
        self.sizer_diff = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_diff.AddMany([(st4,), ((maxTxtW-st4.GetSize()[0],0),), (self.diffImg,)])
        self.sizer_overlays_voted.AddMany([(self.sizer_min,), ((50, 50),), (self.sizer_max,), ((50, 50),),
                                           (self.sizer_diff,)])
        self.sizer_overlays.AddMany([(self.sizer_overlays_voted,), ((50, 50),),
                                     (self.sizer_attrpatch, 0, wx.ALIGN_CENTER)])
        self.set_patch_layout('horizontal')

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(sizer_groups)
        self.sizer.Add(sizer_overlays, flag=wx.ALIGN_CENTER)

        self.SetSizer(self.sizer)
        self.Layout()
        self.SetupScrolling()
        
    def select_group(self, idx):
        if idx < 0 or idx >= len(self.groups):
            return None
        self.idx = idx
        self.listbox_groups.SetSelection(self.idx)
        group = self.groups[idx]

        self.txtctrl_num_elements.SetValue(str(len(group.imgpaths)))

        # OVERLAY_MIN, OVERLAY_MAX are IplImages
        if self.bbs_map:
            curtag = self.get_current_group().tag
            bbs_map_v2 = {}
            for (tag, imgpath), (x1,y1,x2,y2) in self.bbs_map.iteritems():
                if curtag == tag:
                    bbs_map_v2[imgpath] = (x1,y1,x2,y2)
        else:
            bbs_map_v2 = {}
        overlay_min, overlay_max = group.get_overlays(bbs_map=bbs_map_v2)

        minimg_np = iplimage2np(overlay_min)
        maximg_np = iplimage2np(overlay_max)

        min_bitmap = NumpyToWxBitmap(minimg_np)
        max_bitmap = NumpyToWxBitmap(maximg_np)

        self.minOverlayImg.SetBitmap(min_bitmap)
        self.maxOverlayImg.SetBitmap(max_bitmap)
        
        self.Layout()

        return self.idx

    def get_current_group(self):
        return self.groups[self.idx]
        
    def add_group(self, group):
        self.groups.insert(0, group)
        label = "{0} -> {1} elements".format(group.tag, len(group.imgpaths))
        self.listbox_groups.Insert(label, 0)
    def remove_group(self, group):
        idx = self.groups.index(group)
        self.groups.pop(idx)
        self.listbox_groups.Delete(idx)
        if self.groups:
            newidx = min(len(self.groups)-1, idx)
            self.select_group(newidx)
        else:
            # No more groups to display, so do some cleanup
            self.handle_nomoregroups()
    def handle_nomoregroups(self):
        """ Called when there are no more groups in the queue. """
        self.Disable()

    def start(self, imgpath_groups, do_align=False, bbs_map=None, stateP=None):
        """
        Input:
            dict IMGPATH_GROUPS: {str grouptag: [imgpath_i, ...]}
            dict BBS_MAP: maps {(tag, str imgpath): (x1,y1,x2,y2)}. Used to optionally
                overlay subregions of images in IMGPATH_GROUPS, rather than
                extracting+saving each subregion.
        """
        self.stateP = stateP
        if not self.restore_session():
            self.groups = []
            self.groupid2tag = {} # maps {int groupid: str tag}
            self.tag2groupid = {}
            self.bbs_map = bbs_map if bbs_map != None else {}
            for groupid, (tag, imgpaths) in enumerate(imgpath_groups.iteritems()):
                group = Group(groupid, imgpaths, tag=tag, do_align=do_align)
                self.add_group(group)
                self.groupid2tag[groupid] = tag
                self.tag2groupid[tag] = groupid
        self.select_group(0)

    def restore_session(self):
        try:
            print 'trying to load:', self.stateP
            state = pickle.load(open(self.stateP, 'rb'))
            groups = state['groups']
            self.groups = []
            for group_dict in groups:
                self.add_group(Group.unmarshall(group_dict))

            self.groupid2tag = state['groupid2tag']
            self.tag2groupid = state['tag2groupid']
            self.bbs_map = state['bbs_map']
            return state
        except:
            traceback.print_exc()
            return False
    def create_state_dict(self):
        state = {'groups': [g.marshall() for g in self.groups], 
                 'groupid2tag': self.groupid2tag,
                 'tag2groupid': self.tag2groupid,
                 'bbs_map': self.bbs_map}
        return state
    def save_session(self):
        try:
            state = self.create_state_dict()
            pickle.dump(state, open(self.stateP, 'wb'))
            return state
        except:
            return False
        
    def onListBox_groups(self, evt):
        if evt.Selection == -1:
            # Some ListBox events fire when nothing is selected (i.e. -1)
            return
        idx = self.listbox_groups.GetSelection()
        if self.groups:
            self.select_group(idx)

class SplitOverlays(ViewOverlays):
    def __init__(self, parent, *args, **kwargs):
        ViewOverlays.__init__(self, parent, *args, **kwargs)

        self.splitmode = 'kmeans'
        
    def init_ui(self):
        ViewOverlays.init_ui(self)
        
        btn_split = wx.Button(self, label="Split...")
        btn_split.Bind(wx.EVT_BUTTON, self.onButton_split)
        btn_setsplitmode = wx.Button(self, label="Set Split Mode...")
        btn_setsplitmode.Bind(wx.EVT_BUTTON, self.onButton_setsplitmode)
        sizer_split = wx.BoxSizer(wx.VERTICAL)
        sizer_split.AddMany([(btn_split,0,wx.ALIGN_CENTER), (btn_setsplitmode,0,wx.ALIGN_CENTER)])

        self.btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_sizer.Add(sizer_split)

        self.sizer.Add(self.btn_sizer, proportion=0, border=10, flag=wx.ALL)
        self.Layout()

    def start(self, imgpath_groups, do_align=False, bbs_map=None, stateP=None):
        """
        Input:
            dict IMGPATH_GROUPS: {str grouptag: [imgpath_i, ...]}
            dict BBS_MAP: maps {(tag, str imgpath): (x1,y1,x2,y2)}. Used to optionally
                overlay subregions of images in IMGPATH_GROUPS, rather than
                extracting+saving each subregion.
        """
        self.stateP = stateP
        if not self.restore_session():
            self.groups = []
            self.groupid2tag = {}
            self.tag2groupid = {}
            self.bbs_map = bbs_map if bbs_map != None else {}
            for groupid, (tag, imgpaths) in enumerate(imgpath_groups.iteritems()):
                group = GroupRankedList(attrid, imgpaths, tag=tag, do_align=do_align)
                self.add_group(group)
                self.groupid2tag[groupid] = tag
                self.tag2groupid[tag] = groupid
        self.select_group(0)

    def onButton_split(self, evt):
        curgroup = self.get_current_group()
        groups = curgroup.split(mode=self.splitmode)
        for group in groups:
            self.add_group(group)
        self.remove_group(curgroup)

    def onButton_setsplitmode(self, evt):
        if not isinstance(self.get_current_group(), GroupRankedList):
            disabled = [ChooseSplitModeDialog.ID_RANKEDLIST]
        else:
            disabled = None
        dlg = ChooseSplitModeDialog(self, disable=disabled)
        status = dlg.ShowModal()
        if status == wx.ID_CANCEL:
            return
        splitmode = 'kmeans'
        if status == ChooseSplitModeDialog.ID_MIDSPLIT:
            splitmode = 'midsplit'
        elif status == ChooseSplitModeDialog.ID_RANKEDLIST:
            splitmode = 'rankedlist'
        elif status == ChooseSplitModeDialog.ID_KMEANS:
            splitmode = 'kmeans'
        elif status == ChooseSplitModeDialog.ID_PCA_KMEANS:
            splitmode = 'pca_kmeans'
        elif status == ChooseSplitModeDialog.ID_KMEANS2:
            splitmode = 'kmeans2'
        elif status == ChooseSplitModeDialog.ID_KMEDIODS:
            splitmode = 'kmediods'
        self.splitmode = splitmode

class VerifyOverlays(SplitOverlays):
    def __init__(self, parent, *args, **kwargs):
        SplitOverlays.__init__(self, parent, *args, **kwargs)

        # dict self.EXEMPLAR_IMGPATHS: {str grouptag: [str exmpl_imgpath_i, ...]}
        self.exemplar_imgpaths = {}
        # self.RANKEDLIST_MAP: maps {str imgpath: (groupID_0, groupID_1, ...)}
        self.rankedlist_map = {}
        # self.FINISHED_GROUPS: maps {tag: [obj group_i, ...]}, where
        # tag is the group that the user finalized on.
        self.finished_groups = {}

        # self.GROUPID_SEL: groupID that the user has currently selected
        self.groupid_sel = None

        # self.EXMPLIDX_SEL: The exemplaridx that the user has currently selected
        self.exmplidx_sel = None

        # self.ONDONE: A callback function to call when verifying is done.
        self.ondone = None

        # list self.QUARANTINED_GROUPS: List of [obj group_i, ...]
        self.quarantined_groups = None

    def init_ui(self):
        SplitOverlays.init_ui(self)
        
        btn_matches = wx.Button(self, label="Matches")
        btn_matches.Bind(wx.EVT_BUTTON, self.onButton_matches)
        self.btn_manual_relabel = wx.Button(self, label="Manually Relabel...")
        self.btn_manual_relabel.Bind(wx.EVT_BUTTON, self.onButton_manual_relabel)

        btn_nextexmpl = wx.Button(self, label="Next Exemplar Patch")
        btn_nextexmpl.Bind(wx.EVT_BUTTON, self.onButton_nextexmpl)
        btn_prevexmpl = wx.Button(self, label="Previous Exemplar Patch")
        btn_prevexmpl.Bind(wx.EVT_BUTTON, self.onButton_prevexmpl)
        txt0 = wx.StaticText(self, label="Current Exemplar: ")
        self.txt_curexmplidx = wx.StaticText(self, label='')
        txt1 = wx.StaticText(self, label=" / ")
        self.txt_totalexmplidxs = wx.StaticText(self, label='')
        sizer_txtexmpls = wx.BoxSizer(wx.HORIZONTAL)
        sizer_txtexmpls.AddMany([(txt0,), (self.txt_curexmplidx,), (txt1,),
                                 (self.txt_totalexmplidxs,)])
        self.sizer_exmpls = wx.BoxSizer(wx.VERTICAL)
        self.sizer_exmpls.AddMany([(sizer_txtexmpls,), (btn_nextexmpl,), (btn_prevexmpl,)])

        self.btn_quarantine = wx.Button(self, label="Quarantine")
        self.btn_quarantine.Bind(wx.EVT_BUTTON, self.onButton_quarantine)

        self.btn_sizer.AddMany([(btn_matches,), (self.btn_manual_relabel,), (self.sizer_exmpls,),
                                (self.btn_quarantine,)])

        txt_curlabel0 = wx.StaticText(self, label="Current guess: ")
        self.txt_curlabel = wx.StaticText(self, label="")
        self.sizer_curlabel = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_curlabel.AddMany([(txt_curlabel0,), (self.txt_curlabel,)])
        self.sizer.Add(self.sizer_curlabel, proportion=0, flag=wx.ALIGN_CENTER)

        self.Layout()

    def start(self, imgpath_groups, group_exemplars, rlist_map, 
              do_align=False, bbs_map=None, ondone=None, stateP=None):
        """
        Input:
            dict IMGPATH_GROUPS: {grouptag: [imgpath_i, ...]}
            dict GROUP_EXEMPLARS: maps {grouptag: [exmpl_imgpath_i, ...]}
            dict RLIST_MAP: maps {str imgpath: (groupID_0, ...)}
            dict BBS_MAP: maps {(str tag, imgpath): (x1,y1,x2,y2)}
            fn ONDONE: Function that accepts one argument:
                dict {str tag: [obj group_i, ...]}
        """
        self.stateP = stateP
        if not self.restore_session():
            self.exemplar_imgpaths = group_exemplars
            self.groups = []
            self.groupid2tag = {}
            self.tag2groupid = {}
            self.bbs_map = bbs_map if bbs_map != None else {}
            self.rankedlist_map = rlist_map
            self.ondone = ondone
            self.finished_groups = {}
            self.exmplidx_sel = 0
            self.quarantined_groups = []
            for groupid, (tag, imgpaths) in enumerate(imgpath_groups.iteritems()):
                group = GroupRankedList(groupid, imgpaths, tag=tag, do_align=do_align)
                if imgpaths:
                    self.add_group(group)
                self.groupid2tag[groupid] = tag
                self.tag2groupid[tag] = groupid
        if len(self.groups) == 0:
            self.handle_nomoregroups()
        else:
            self.select_group(0)

    def stop(self):
        # Do an export.
        self.save_session()
        self.export_results()

    def export_results(self):
        """ Calls the callback function and passes the verify_results
        off.
        """
        if self.ondone:
            verify_results = {} # maps {tag: [imgpath_i, ...]}
            for tag, groups in self.finished_groups.iteritems():
                for group in groups:
                    verify_results.setdefault(tag, []).extend(group.imgpaths)
            self.ondone(verify_results)

    def restore_session(self):
        try:
            state = pickle.load(open(self.stateP, 'rb'))
            groups = state['groups']
            self.groups = []
            for group_dict in groups:
                self.add_group(GroupRankedList.unmarshall(group_dict))

            self.groupid2tag = state['groupid2tag']
            self.tag2groupid = state['tag2groupid']
            self.bbs_map = state['bbs_map']
            self.exemplar_imgpaths = state['exemplar_imgpaths']
            self.rankedlist_map = state['rankedlist_map']
            fingroups_in = state['finished_groups']
            fingroups_new = {}
            for tag, groups_marsh in fingroups_in.iteritems():
                fingroups_new[tag] = [GroupRankedList.unmarshall(gdict) for gdict in groups_marsh]
            self.finished_groups = fingroups_new
            self.quarantined_groups = [GroupRankedList.unmarshall(gdict) for gdict in state['quarantined_groups']]
            print '...Successfully loaded VerifyOverlays state...'
            return state
        except Exception as e:
            print '...Failed to load VerifyOverlays state...'
            return False
    def create_state_dict(self):
        state = SplitOverlays.create_state_dict(self)
        state['exemplar_imgpaths'] = self.exemplar_imgpaths
        state['rankedlist_map'] = self.rankedlist_map
        fingroups_out = {}
        for tag, groups in self.finished_groups.iteritems():
            fingroups_out[tag] = [g.marshall() for g in groups]
        state['finished_groups'] = fingroups_out
        state['quarantined_groups'] = [g.marshall() for g in self.quarantined_groups]
        return state

    def select_group(self, idx):
        curidx = SplitOverlays.select_group(self, idx)
        if curidx == None:
            # Say, if IDX is invalid (maybe no more groups?)
            return
        group = self.groups[curidx]
        self.select_exmpl_group(group.groupid, group.exmpl_idx)

        self.Layout()

    def select_exmpl_group(self, groupid, exmpl_idx):
        """ Displays the correct exemplar img patch on the screen. """
        if groupid < 0 or groupid >= len(self.exemplar_imgpaths):
            print "...Invalid GroupID: {0}...".format(groupid)
            return
        tag = self.groupid2tag[groupid]
        exemplar_paths = self.exemplar_imgpaths[tag]
        if exmpl_idx < 0 or exmpl_idx >= len(exemplar_paths):
            print "...Invalid exmpl_idx: {0}...".format(exmpl_idx)
            return
        exemplar_npimg = scipy.misc.imread(exemplar_paths[exmpl_idx])
        exemplarImg_bitmap = NumpyToWxBitmap(exemplar_npimg)
        self.groupid_sel = groupid
        self.exmplidx_sel = exmpl_idx
        self.exemplarImg.SetBitmap(exemplarImg_bitmap)
        self.txt_exemplarTag.SetLabel(str(self.groupid2tag[groupid]))
        self.txt_curexmplidx.SetLabel(str(exmpl_idx+1))
        self.txt_totalexmplidxs.SetLabel(str(len(self.exemplar_imgpaths[tag])))
        self.txt_curlabel.SetLabel(str(tag))
        self.Layout()

    def get_groupid_sel(self):
        """ Returns the groupid of the currently-selected group, i.e.
        the group with the exemplar image currently showing.
        """
        return self.groupid_sel

    def handle_nomoregroups(self):
        SplitOverlays.handle_nomoregroups(self)

    def onButton_matches(self, evt):
        curgroup = self.groups[self.idx]
        cursel_groupid = self.get_groupid_sel()
        curtag = self.groupid2tag[cursel_groupid]
        self.finished_groups.setdefault(curtag, []).append(curgroup)
        self.remove_group(curgroup)
        print "FinishedGroups:", self.finished_groups

    def onButton_manual_relabel(self, evt):
        dlg = ManualRelabelDialog(self, self.groupid2tag.values())
        status = dlg.ShowModal()
        if status == wx.CANCEL:
            return
        sel_tag = dlg.tag
        sel_groupid = self.tag2groupid[sel_tag]
        self.select_exmpl_group(sel_groupid, self.groups[self.idx].exmpl_idx)
    def onButton_nextexmpl(self, evt):
        nextidx = self.exmplidx_sel + 1
        self.select_exmpl_group(self.get_groupid_sel(), nextidx)
    def onButton_prevexmpl(self, evt):
        previdx = self.exmplidx_sel - 1
        self.select_exmpl_group(self.get_groupid_sel(), previdx)
    def onButton_quarantine(self, evt):
        curgroup = self.get_current_group()
        self.quarantined_groups.append(curgroup)
        self.remove_group(curgroup)

class CheckImageEquals(VerifyOverlays):
    """ A widget that lets the user separate a set of images into two
    categories:
        A.) These images match category A
        B.) These images do /not/ match category A.
    """
    TAG_YES = "YES_TAG"
    TAG_NO = "NO_TAG"
    def __init__(self, parent, *args, **kwargs):
        VerifyOverlays.__init__(self, parent, *args, **kwargs)

        self.cat_imgpath = None
        
    def init_ui(self):
        VerifyOverlays.init_ui(self)

        btn_no = wx.Button(self, label="Doesn't Match")
        btn_no.Bind(wx.EVT_BUTTON, self.onButton_no)
        
        self.btn_sizer.Add(btn_no)

        self.btn_manual_relabel.Hide()
        self.btn_quarantine.Hide()
        self.sizer_exmpls.ShowItems(False)
        self.sizer_curlabel.ShowItems(False)

        self.Layout()

    def start(self, imgpaths, cat_imgpath, do_align=False, bbs_map=None,
              ondone=None, stateP=None):
        """
        Input:
            list IMGPATHS: [imgpath_i, ...]
            str CAT_IMGPATH: Imagepath of the category.
            dict BBS_MAP: maps {str imgpath: (x1,y1,x2,y2}
            fn ONDONE: Function that accepts one argument:
                dict {str tag: [obj group_i, ...]}
                
        """
        self.stateP = stateP
        if not self.restore_session():
            # 0.) Munge IMGPATHS, BBS_MAP into VerifyOverlay-friendly versions
            imgpath_groups = {} # maps {str tag: [imgpath_i, ...]}
            bbs_map_v2 = {} # maps {(str tag, imgpath): (x1,y1,x2,y2)}
            for imgpath in imgpaths:
                imgpath_groups.setdefault(self.TAG_YES, []).append(imgpath)
                if bbs_map:
                    bbs_map_v2[(self.TAG_YES, imgpath)] = bbs_map[imgpath]
            imgpath_groups[self.TAG_NO] = []
            group_exemplars = {self.TAG_YES: [cat_imgpath]}
            rlist_map = {} # Don't care
            VerifyOverlays.start(self, imgpath_groups, group_exemplars, rlist_map, 
                                 do_align=do_align, bbs_map=bbs_map_v2, ondone=ondone)
        self.cat_imgpath = cat_imgpath
        I = scipy.misc.imread(cat_imgpath, flatten=True)
        bitmap = NumpyToWxBitmap(I)
        self.exemplarImg.SetBitmap(bitmap)
        self.Layout()

    def onButton_no(self, evt):
        curgroup = self.get_current_group()
        self.finished_groups.setdefault(self.TAG_NO, []).append(curgroup)
        self.remove_group(curgroup)
    def handle_nomoregroups(self):
        self.export_results()
        self.Close()

class Group(object):
    def __init__(self, groupid, imgpaths, tag=None, do_align=False):
        self.groupid = groupid
        self.tag = tag
        self.imgpaths = imgpaths
    
        # self.OVERLAY_MIN, self.OVERLAY_MAX: IplImage overlays.
        self.overlay_min = None
        self.overlay_max = None
        self.do_align = do_align
    def get_overlays(self, bbs_map=None):
        """
        Input:
            dict BBS_MAP: maps {str imgpath: (x1,y1,x2,y2)}
        Output:
            IplImage minimg, IplImage maximg.
        """
        if not self.overlay_min:
            minimg, maximg = make_overlays.minmax_cv(self.imgpaths, do_align=self.do_align,
                                                     rszFac=0.75, bbs_map=bbs_map)
            self.overlay_min = minimg
            self.overlay_max = maximg
        return self.overlay_min, self.overlay_max

    def midsplit(self):
        """ Laziest split method: Split down the middle. """
        mid = len(self.imgpaths) / 2
        imgsA, imgsB = self.imgpaths[:mid], self.imgpaths[mid:]
        return [type(self)(self.groupid, imgsA, tag=self.tag, do_align=self.do_align),
                type(self)(self.groupid, imgsB, tag=self.tag, do_align=self.do_align)]

    def split_kmeans(self, K=2):
        t = time.time()
        print "...running k-means..."
        clusters = cluster_imgs.cluster_imgs_kmeans(self.imgpaths, k=K, do_downsize=True,
                                                    do_align=True)
        dur = time.time() - t
        print "...Completed k-means ({0} s)".format(dur)
        groups = []
        for clusterid, imgpaths in clusters.iteritems():
            groups.append(type(self)(self.groupid, imgpaths, tag=self.tag, do_align=self.do_align))
        assert len(groups) == K
        return groups

    def split_pca_kmeans(self, K=2, N=3):
        t = time.time()
        print "...running PCA+k-means..."
        clusters = cluster_imgs.cluster_imgs_pca_kmeans(self.imgpaths, k=K, do_align=True)
        dur = time.time() - t
        print "...Completed PCA+k-means ({0} s)".format(dur)
        groups = []
        for clusterid, imgpaths in clusters.iteritems():
            groups.append(type(self)(self.groupid, imgpaths, tag=self.tag, do_align=self.do_align))
        assert len(groups) == K
        return groups
        
    def split_kmeans2(self, K=2):
        t = time.time()
        print "...running k-meansV2..."
        clusters = cluster_imgs.kmeans_2D(self.imgpaths, k=K, distfn_method='vardiff',
                                          do_align=True)
        dur = time.time() - t
        print "...Completed k-meansV2 ({0} s)".format(dur)
        groups = []
        for clusterid, imgpaths in clusters.iteritems():
            groups.append(type(self)(self.groupid, imgpaths, tag=self.tag, do_align=self.do_align))
        assert len(groups) == K
        return groups

    def split_kmediods(self, K=2):
        t = time.time()
        print "...running k-mediods..."
        clusters = cluster_imgs.kmediods_2D(self.imgpaths, k=K, distfn_method='vardiff',
                                            do_align=True)
        dur = time.time() - t
        print "...Completed k-mediods ({0} s)".format(dur)
        groups = []
        for clusterid, imgpaths in clusters.iteritems():
            groups.append(type(self)(self.groupid, imgpaths, tag=self.tag, do_align=self.do_align))
        assert len(groups) == K
        return groups

    def split(self, mode=None):
        if mode == None:
            mode == 'kmeans'
        if len(self.imgpaths) == 1:
            return [self]
        elif len(self.imgpaths) == 2:
            return [type(self)(self.groupid, [self.imgpaths[0]], tag=self.tag, do_align=self.do_align),
                    type(self)(self.groupid, [self.imgpaths[1]], tag=self.tag, do_align=self.do_align)]
        if mode == 'midsplit':
            return self.midsplit()
        elif mode == 'kmeans':
            return self.split_kmeans(K=2)
        elif mode == 'pca_kmeans':
            return self.split_pca_kmeans(K=2, N=3)
        elif mode == 'kmeans2':
            return self.split_kmeans2(K=2)
        elif mode == 'kmediods':
            return self.split_kmediods(K=2)
        else:
            return self.split_kmeans(K=2)

    def marshall(self):
        """ Returns a dict-rep of myself. In particular, you can't pickle
        IplImages, so don't include them.
        """
        me = {'groupid': self.groupid, 'tag': self.tag,
              'imgpaths': self.imgpaths, 'do_align': self.do_align}
        return me

    @staticmethod
    def unmarshall(d):
        return Group(d['groupid'], d['imgpaths'], tag=d['tag'], do_align=d['do_align'])

    def __eq__(self, o):
        return (isinstance(o, Group) and self.imgpaths == o.imgpaths)
    def __repr__(self):
        return "Group({0},gid={1},numimgs={2})".format(self.tag,
                                                       self.groupid,
                                                       len(self.imgpaths))
    def __str__(self):
        return "Group({0},gid={1},numimgs={2})".format(self.tag,
                                                       self.groupid,
                                                       len(self.imgpaths))
    
class GroupRankedList(Group):
    def __init__(self, groupid, imgpaths, rlist_idx=0, exmpl_idx=0, *args, **kwargs):
        Group.__init__(self, groupid, imgpaths, *args, **kwargs)
        self.rlist_idx = rlist_idx
        self.exmpl_idx = exmpl_idx
    def split(self, mode=None):
        if mode == None:
            mode = 'rankedlist'
        if mode == 'rankedlist':
            return [self]
        else:
            return Group.split(self, mode=mode)
    def marshall(self):
        me = Group.marshall(self)
        me['rlist_idx'] = self.rlist_idx
        me['exmpl_idx'] = self.exmpl_idx
        return me
    @staticmethod
    def unmarshall(d):
        return GroupRankedList(d['groupid'], d['imgpaths'], rlist_idx=d['rlist_idx'],
                               exmpl_idx=d['exmpl_idx'], tag=d['tag'], do_align=d['do_align'])
    def __repr__(self):
        return "GroupRankedList({0},gid={1},rlidx={2},exidx={3},numimgs={4})".format(self.tag,
                                                                                     self.groupid,
                                                                                     self.rlist_idx,
                                                                                     self.exmpl_idx,
                                                                                     len(self.imgpaths))
    def __str__(self):
        return "GroupRankedList({0},gid={1},rlidx={2},exidx={3},numimgs={4})".format(self.tag,
                                                                                     self.groupid,
                                                                                     self.rlist_idx,
                                                                                     self.exmpl_idx,
                                                                                     len(self.imgpaths))

class DigitGroup(Group):
    def __repr__(self):
        return "DigitGroup({0},gid={1},rlidx={2},exidx={3},numimgs={4})".format(self.tag,
                                                                                self.groupid,
                                                                                self.rlist_idx,
                                                                                self.exmpl_idx,
                                                                                len(self.imgpaths))
    def __str__(self):
        return "DigitGroup({0},gid={1},rlidx={2},exidx={3},numimgs={4})".format(self.tag,
                                                                                self.groupid,
                                                                                self.rlist_idx,
                                                                                self.exmpl_idx,
                                                                                len(self.imgpaths))
    
    

class ManualRelabelDialog(wx.Dialog):
    def __init__(self, parent, tags, *args, **kwargs):
        """
        Input:
            list TAGS: list [tag_i, ...]
        """
        wx.Dialog.__init__(self, parent, *args, **kwargs)
        
        self.tag = None

        self.tags = tags

        txt0 = wx.StaticText(self, label="What is the correct tag?")
        self.combobox_tags = wx.ComboBox(self, choices=map(str, tags), 
                                         style=wx.CB_READONLY | wx.CB_SORT, size=(200, -1))
        cbox_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cbox_sizer.AddMany([(txt0,), (self.combobox_tags,)])
        
        btn_ok = wx.Button(self, label="Ok")
        btn_ok.Bind(wx.EVT_BUTTON, self.onButton_ok)
        btn_cancel = wx.Button(self, label="Cancel")
        btn_cancel.Bind(wx.EVT_BUTTON, self.onButton_cancel)
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.AddMany([(btn_ok,), (btn_cancel,)])

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(cbox_sizer)
        self.sizer.Add(btn_sizer, flag=wx.ALIGN_CENTER)

        self.SetSizer(self.sizer)
        self.Layout()

    def onButton_ok(self, evt):
        self.tag = self.tags[self.combobox_tags.GetSelection()]
        self.EndModal(wx.OK)
    def onButton_cancel(self, evt):
        self.EndModal(wx.CANCEL)

class ChooseSplitModeDialog(wx.Dialog):
    ID_MIDSPLIT = 41
    ID_RANKEDLIST = 42
    ID_KMEANS = 43
    ID_PCA_KMEANS = 44
    ID_KMEANS2 = 45
    ID_KMEDIODS = 46

    def __init__(self, parent, disable=None, *args, **kwargs):
        """ disable is a list of ID's (ID_RANKEDLIST, etc.) to disable. """
        wx.Dialog.__init__(self, parent, *args, **kwargs)
        if disable == None:
            disable = []
        sizer = wx.BoxSizer(wx.VERTICAL)
        txt = wx.StaticText(self, label="Please choose the desired 'Split' method.")

        self.midsplit_rbtn = wx.RadioButton(self, label="Split in the middle (fast, but not good)", style=wx.RB_GROUP)
        self.rankedlist_rbtn = wx.RadioButton(self, label='Ranked-List (fast)')
        self.kmeans_rbtn = wx.RadioButton(self, label='K-means (not-as-fast)')
        self.pca_kmeans_rbtn = wx.RadioButton(self, label='PCA+K-means (not-as-fast)')
        self.kmeans2_rbtn = wx.RadioButton(self, label="K-means V2 (not-as-fast)")
        self.kmediods_rbtn = wx.RadioButton(self, label="K-Mediods")
        
        if parent.splitmode == 'midsplit':
            self.midsplit_rbtn.SetValue(1)
        elif parent.splitmode == 'rankedlist':
            self.rankedlist_rbtn.SetValue(1)
        elif parent.splitmode == 'kmeans':
            self.kmeans_rbtn.SetValue(1)
        elif parent.splitmode == 'pca_kmeans':
            self.pca_kmeans_rbtn.SetValue(1)
        elif parent.splitmode == 'kmeans2':
            self.kmeans2_rbtn.SetValue(1)
        elif parent.splitmode == 'kmediods':
            self.kmediods_rbtn.SetValue(1)
        else:
            print "Unrecognized parent.splitmode: {0}. Defaulting to kmeans.".format(parent.splitmode)
            self.kmeans_rbtn.SetValue(1)

        if self.ID_MIDSPLIT in disable:
            self.midsplit_rbtn.Disable()
        if ChooseSplitModeDialog.ID_RANKEDLIST in disable:
            self.rankedlist_rbtn.Disable()
        if ChooseSplitModeDialog.ID_KMEANS in disable:
            self.kmeans_rbtn.Disable()
        if ChooseSplitModeDialog.ID_PCA_KMEANS in disable:
            self.pca_kmeans_rbtn.Disable()
        if ChooseSplitModeDialog.ID_KMEANS2 in disable:
            self.kmeans2_rbtn.Disable()
        if ChooseSplitModeDialog.ID_KMEDIODS in disable:
            self.kmediods_rbtn.Disable()
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(self, label="Ok")
        btn_cancel = wx.Button(self, label="Cancel")
        btn_ok.Bind(wx.EVT_BUTTON, self.onButton_ok)
        btn_cancel.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_CANCEL))
        
        btn_sizer.AddMany([(btn_ok,), (btn_cancel,)])

        sizer.AddMany([(txt,), ((20,20),), (self.midsplit_rbtn,), (self.rankedlist_rbtn,),
                       (self.kmeans_rbtn,), (self.pca_kmeans_rbtn,),
                       (self.kmeans2_rbtn,), (self.kmediods_rbtn),])
        sizer.Add(btn_sizer, flag=wx.ALIGN_CENTER)

        self.SetSizer(sizer)
        self.Fit()

    def onButton_ok(self, evt):
        if self.midsplit_rbtn.GetValue():
            self.EndModal(self.ID_MIDSPLIT)
        elif self.rankedlist_rbtn.GetValue():
            self.EndModal(self.ID_RANKEDLIST)
        elif self.kmeans_rbtn.GetValue():
            self.EndModal(self.ID_KMEANS)
        elif self.pca_kmeans_rbtn.GetValue():
            self.EndModal(self.ID_PCA_KMEANS)
        elif self.kmeans2_rbtn.GetValue():
            self.EndModal(self.ID_KMEANS2)
        elif self.kmediods_rbtn.GetValue():
            self.EndModal(self.ID_KMEDIODS)
        else:
            print "Unrecognized split mode. Defaulting to K-means."
            self.EndModal(self.ID_KMEANS)

def PilImageToWxBitmap( myPilImage ) :
    return WxImageToWxBitmap( PilImageToWxImage( myPilImage ) )
def PilImageToWxImage( myPilImage ):
    myWxImage = wx.EmptyImage( myPilImage.size[0], myPilImage.size[1] )
    myWxImage.SetData( myPilImage.convert( 'RGB' ).tostring() )
    return myWxImage
def WxImageToWxBitmap( myWxImage ) :
    return myWxImage.ConvertToBitmap()
def NumpyToWxBitmap(img):
    """
    Assumption: img represents a grayscale img [not sure if necessary]
    """
    img_pil = Image.fromarray(img)
    return PilImageToWxBitmap(img_pil)

def iplimage2np(iplimage):
    """ Assumes IPLIMAGE has depth cv.CV_8U. """
    w, h = cv.GetSize(iplimage)
    img_np = np.fromstring(iplimage.tostring(), dtype='uint8')
    img_np = img_np.reshape(h, w)
    
    return img_np

def is_img_ext(p):
    return os.path.splitext(p)[1].lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.tif')

def test_verifyoverlays():
    class TestFrame(wx.Frame):
        def __init__(self, parent, imggroups, exemplars, *args, **kwargs):
            wx.Frame.__init__(self, parent, size=(600, 500), *args, **kwargs)

            self.imggroups = imggroups

            self.viewoverlays = VerifyOverlays(self)#ViewOverlays(self)

            self.sizer = wx.BoxSizer(wx.VERTICAL)
            self.sizer.Add(self.viewoverlays, proportion=1, flag=wx.EXPAND)
            self.SetSizer(self.sizer)
            self.Layout()

            self.viewoverlays.start(self.imggroups, exemplars, {}, do_align=True, ondone=self.ondone)

        def ondone(self, verify_results):
            print '...In ondone...'
            print 'verify_results:', verify_results
    args = sys.argv[1:]
    imgsdir = args[0]
    exmpls_dir = args[1]
    
    imggroups = {} # maps {str groupname: [imgpath_i, ...]}
    for dirpath, dirnames, filenames in os.walk(imgsdir):
        imggroup = []
        groupname = os.path.split(dirpath)[1]
        print filenames, groupname
        for imgname in [f for f in filenames if is_img_ext(f)]:
            imggroup.append(os.path.join(dirpath, imgname))
        if imggroup:
            imggroups[groupname] = imggroup

    exmpl_paths = {}
    for dirpath, dirnames, filenames in os.walk(exmpls_dir):
        exmpls = []
        groupname = os.path.split(dirpath)[1]
        for imgname in [f for f in filenames if is_img_ext(f)]:
            exmpls.append(os.path.join(dirpath, imgname))
        if exmpls:
            exmpl_paths[groupname] = exmpls

    app = wx.App(False)
    f = TestFrame(None, imggroups, exmpl_paths)
    f.Show()
    app.MainLoop()

def test_checkimgequal():
    class TestFrame(wx.Frame):
        def __init__(self, parent, imgpaths, catimgpath, *args, **kwargs):
            wx.Frame.__init__(self, parent, size=(600, 500), *args, **kwargs)

            self.chkimgequals = CheckImageEquals(self)

            self.sizer = wx.BoxSizer(wx.VERTICAL)
            self.sizer.Add(self.chkimgequals, proportion=1, flag=wx.EXPAND)
            self.SetSizer(self.sizer)
            self.Layout()

            self.chkimgequals.start(imgpaths, catimgpath, do_align=True, ondone=self.ondone)

        def ondone(self, verify_results):
            print '...In TestFrame.ondone...'
            print 'verify_results:', verify_results
    args = sys.argv[1:]
    imgsdir = args[0]
    catimgpath = args[1]
    
    imgpaths = []
    for dirpath, dirnames, filenames in os.walk(imgsdir):
        for imgname in [f for f in filenames if is_img_ext(f)]:
            imgpaths.append(os.path.join(dirpath, imgname))

    app = wx.App(False)
    f = TestFrame(None, imgpaths, catimgpath)
    f.Show()
    app.MainLoop()

def main():
    #test_verifyoverlays()
    test_checkimgequal()

if __name__ == '__main__':
    main()
