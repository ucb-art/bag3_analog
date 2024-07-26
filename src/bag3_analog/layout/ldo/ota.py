# BSD 3-Clause License
#
# Copyright (c) 2023, Regents of the University of California
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# -*- coding: utf-8 -*-

"""This module contains layout implementations for several standard cells."""

from typing import Any, Dict, Sequence, Optional, Union, Tuple, Mapping, Type, List

from itertools import chain
from bag.typing import TrackType

from pybag.enum import MinLenMode, RoundMode

from bag.util.math import HalfInt
from bag.util.immutable import Param
from bag.design.database import ModuleDB
from bag.design.module import Module
from bag.layout.template import TemplateDB, PyLayInstance
from bag.layout.routing.base import TrackID, WireArray

from xbase.layout.enum import MOSWireType, MOSType
from xbase.layout.mos.base import MOSBasePlaceInfo, MOSBase
from xbase.layout.mos.data import MOSPorts
from xbase.layout.mos.placement.data import TilePatternElement

from bag3_analog.schematic.ota import bag3_analog__ota

class OTA(MOSBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        MOSBase.__init__(self, temp_db, params, **kwargs)

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__ota

    @classmethod
    def get_params_info(cls):
        # type: () -> Dict[str, str]
        return dict(
            pinfo='The MOSBasePlaceInfo object.',
            wp='pmos width.',
            wn='nmos width.',
            ridx_load='load row index.',
            ridx_diff='diff pair row index.',
            ridx_tail='tail and current reference row index.',
            row_layout_info='row layout information dictionary.',
            sig_locs='signal track location dictionary.',
            seg_diff='number of segments for differential pair.',
            seg_load='number of segments for load.',
            seg_tail='number of segments for tail.',
            seg_iref='number of segments for current reference device.',
            # ntap_tiles='tile indices for ntaps',
            # ptap_tiles='tile indices for ptaps',
            # tail_tile_idx='tile index for tail',
            # diff_pair_tile_idx='tile index for diff pair',
            # load_tile_idx='tile index for load',
        )

    @classmethod
    def get_default_param_values(cls):
        # type: () -> Dict[str, Any]
        return dict(
            wp=None,
            wn=None,
            ridx_load=-1,
            ridx_diff=1,
            ridx_tail=0,
            row_layout_info=None,
            sig_locs=None,
        )

    def draw_layout(self) -> None:
        pinfo = MOSBasePlaceInfo.make_place_info(self.grid, self.params['pinfo'])
        self.draw_base(pinfo)
        blk_sp = self.min_sep_col

        # get parameters
        wp: int = self.params['wp']
        wn: int = self.params['wn']
        ridx_load: int = self.params['ridx_load']
        ridx_diff: int = self.params['ridx_diff']
        ridx_tail: int = self.params['ridx_tail']
        row_layout_info: Dict[str, Any] = self.params['row_layout_info']
        sig_locs: Dict[str, Any] = self.params['sig_locs']
        seg_diff: int = self.params['seg_diff']
        seg_load: int = self.params['seg_load']
        seg_tail: int = self.params['seg_tail']
        seg_iref: int = self.params['seg_iref']

        # ntap_tiles: List[int] = self.params['ntap_tiles']
        # ptap_tiles: List[int] = self.params['ptap_tiles']
        # tail_tile_idx: int = self.params['tail_tile_idx']
        # diff_pair_tile_idx: int = self.params['diff_pair_tile_idx']
        # load_tile_idx: int = self.params['load_tile_idx']

        # calculate number of columns
        num_cols = max(2 * seg_diff, 2 * seg_load, 2 * seg_tail) + seg_iref
        # FIXME: The 2x sub_sep_col is a tapeout hack
        start_col = self.get_tap_ncol() + self.sub_sep_col * 2
        last_col = max(2 * seg_diff, 2 * seg_load, seg_tail) + seg_iref + start_col


        # place iref device in center
        iref_loc = max(seg_diff, seg_load, seg_tail // 2) + start_col
        n_iref = self.add_mos(ridx_tail, iref_loc, seg_iref, w=wn)


        # place tail devices
        half_seg_tail = seg_tail // 2
        if seg_tail < (iref_loc - start_col): # if tail isn't the widest device
            tail_loc_l = (iref_loc - half_seg_tail) // 2 - blk_sp        # center tail in column
        else:
            tail_loc_l = 0
        tail_loc_r = (last_col - (iref_loc + seg_iref)) // 2 + half_seg_tail + blk_sp + iref_loc + seg_iref   # and on the other side
        tail_loc_l += start_col
        n_tail_l = self.add_mos(ridx_tail, tail_loc_l, half_seg_tail, w=wn)  # left
        n_tail_r = self.add_mos(ridx_tail, tail_loc_r, half_seg_tail, w=wn, flip_lr=True)  # right

        # place diff pair devices
        # TODO: maybe these need a sep column is seg is odd
        if 2 * seg_diff < (iref_loc - start_col):
            diff_loc_l = (iref_loc - 2 * seg_diff) // 2
        else:
            diff_loc_l = 0
        diff_loc_r = iref_loc + seg_iref + diff_loc_l
        diff_loc_l += start_col
        half_seg_diff = seg_diff // 2
        n_diff_l_n = self.add_mos(ridx_diff, diff_loc_l, half_seg_diff, w=wn)
        n_diff_l_p = self.add_mos(ridx_diff, diff_loc_l + half_seg_diff, half_seg_diff, w=wn)
        n_diff_r_n = self.add_mos(ridx_diff, diff_loc_r, half_seg_diff, w=wn)
        n_diff_r_p = self.add_mos(ridx_diff, diff_loc_r + half_seg_diff, half_seg_diff, w=wn)

        # place loading devices
        if 2 * seg_load < (iref_loc - start_col):
            load_loc_l = (iref_loc - 2 * seg_load) // 2
        else:
            load_loc_l = 0
        load_loc_r = iref_loc + seg_iref + load_loc_l
        load_loc_l += start_col
        half_seg_load = seg_load // 2
        p_load_l_n = self.add_mos(ridx_load, load_loc_l, half_seg_load, w=wp)
        p_load_l_p = self.add_mos(ridx_load, load_loc_l + half_seg_load, half_seg_load, w=wp)
        p_load_r_n = self.add_mos(ridx_load, load_loc_r, half_seg_load, w=wp)
        p_load_r_p = self.add_mos(ridx_load, load_loc_r + half_seg_load, half_seg_load, w=wp)

        vdd_list = []
        vss_list = []
        self.add_tap(0, vdd_list, vss_list)
        # FIXME: The 2x sub_sep_col is a tapeout hack
        self.add_tap(last_col + self.sub_sep_col * 2 + self.get_tap_ncol(), vdd_list, vss_list, flip_lr=True)
        # self.add_tap(0, )

        self.set_mos_size()

        # get supply tracks
        vss_tidx = self.get_track_index(ridx_tail, MOSWireType.DS, 'sup', 0)
        vdd_tidx = self.get_track_index(ridx_load, MOSWireType.DS, 'sup', 0)

        # set up layers
        top_layer = self.get_tile_pinfo(0).top_layer
        x_layers = range(self.conn_layer + 1, top_layer + 1, 2)
        y_layers = range(self.conn_layer + 2, top_layer + 1, 2)

        # make rails
        sup_width = self.tr_manager.get_width(x_layers[0], 'sup')
        vdd = self.add_wires(x_layers[0], vdd_tidx, self.bound_box.xl, self.bound_box.xh, width=sup_width)
        vss = self.add_wires(x_layers[0], vss_tidx, self.bound_box.xl, self.bound_box.xh, width=sup_width)

        # make connections
        # current mirror
        self.connect_to_track_wires(n_iref.s, vss)  # connect source to vss
        self.connect_wires([n_iref.d, n_iref.g])    # diode connection
        iref_tid = self.get_track_id(ridx_tail, MOSWireType.DS, 'sig', 0)
        iref_warr = self.connect_to_tracks(n_iref.d, iref_tid)  # add pin for current reference in

        # load
        self.connect_to_track_wires([p_load_l_n.s, p_load_l_p.s, p_load_r_n.s, p_load_r_p.s], vdd)
        self.connect_wires([p_load_l_n.d, p_load_l_n.g, p_load_l_p.g])
        self.connect_wires([p_load_r_n.d, p_load_r_n.g, p_load_r_p.g])
        out_tid = self.get_track_id(ridx_load, MOSWireType.DS, 'sig', -1)
        mid_tid = self.get_track_id(ridx_load, MOSWireType.DS, 'sig', -2)
        gate_tid = self.get_track_id(ridx_load, MOSWireType.G, 'sig', -1)
        out_warr = self.connect_to_tracks([p_load_l_p.d, p_load_r_p.d], out_tid)
        load_gate_tie = self.connect_to_tracks([p_load_l_p.g, p_load_l_n.g,
                                                p_load_r_p.g, p_load_r_n.g], gate_tid)
        # gate_r_tie = self.connect_to_tracks([p_load_r_p.g, p_load_r_n.g], gate_tid)
        # mid_l_warr = self.connect_to_tracks(p_load_l_n.d, mid_tid)
        # mid_r_warr = self.connect_to_tracks(p_load_r_n.d, mid_tid)

        # tail
        self.connect_to_track_wires([n_tail_l.s, n_tail_r.s], vss)
        mir_tid = self.get_track_id(ridx_tail, MOSWireType.G, 'sig', 0)
        self.connect_to_tracks([n_iref.g, n_tail_l.g, n_tail_r.g], mir_tid)
        tail_tid = self.get_track_id(ridx_tail, MOSWireType.DS, 'sig', 1)
        tail_l_warr = self.connect_to_tracks(n_tail_l.d, tail_tid)
        tail_r_warr = self.connect_to_tracks(n_tail_r.d, tail_tid)

        # diff pair
        diff_s_tid = self.get_track_id(ridx_diff, MOSWireType.DS, 'sig', 0)
        diff_d_n_tid = self.get_track_id(ridx_diff, MOSWireType.DS, 'sig', -1)
        diff_d_p_tid = self.get_track_id(ridx_diff, MOSWireType.DS, 'sig', -2)
        diff_gn_tid = self.get_track_id(ridx_diff, MOSWireType.G, 'sig', 1)
        diff_gp_tid = self.get_track_id(ridx_diff, MOSWireType.G, 'sig', 0)
        diff_s_warr = self.connect_to_tracks([n_diff_l_n.s, n_diff_l_p.s,
                                                n_diff_r_n.s, n_diff_r_p.s], diff_s_tid)
        diff_l_mid_tid = self._track_to_track(n_diff_l_n.d.track_id, y_layers[0])
        diff_r_mid_tid = self._track_to_track(n_diff_r_n.d.track_id, y_layers[0])
        self.connect_to_tracks([tail_l_warr, diff_s_warr], diff_l_mid_tid)
        self.connect_to_tracks([tail_r_warr, diff_s_warr], diff_r_mid_tid)
        diff_n_d_warr = self.connect_to_tracks([n_diff_l_n.d, n_diff_r_n.d], diff_d_n_tid)
        diff_p_d_warr = self.connect_to_tracks([n_diff_l_p.d, n_diff_r_p.d], diff_d_p_tid)
        diff_p_d_vm_tid = self._track_to_track(n_iref.d[0].track_id, y_layers[0])
        diff_n_d_vm_tid = self._track_to_track(n_iref.d[1].track_id, y_layers[0])
        self.connect_to_tracks([diff_n_d_warr, load_gate_tie], diff_n_d_vm_tid)
        self.connect_to_tracks([diff_p_d_warr, out_warr], diff_p_d_vm_tid)
        in_n_warr = self.connect_to_tracks([n_diff_l_n.g , n_diff_r_n.g], diff_gn_tid)
        in_p_warr = self.connect_to_tracks([n_diff_l_p.g , n_diff_r_p.g], diff_gp_tid)

        self.connect_to_track_wires(vdd_list, vdd)
        self.connect_to_track_wires(vss_list, vss)

        # make pins
        self.add_pin('out', out_warr)
        self.add_pin('in_n', in_n_warr)
        self.add_pin('in_p', in_p_warr)
        self.add_pin('iref', iref_warr)

        self.add_pin('VDD', vdd)
        self.add_pin('VSS', vss)

        self.sch_params = dict(
            wp=wp,
            wn=wn,
            lch=self.place_info.lch,
            seg_diff=seg_diff,
            seg_iref=seg_iref,
            seg_load=seg_load,
            seg_tail=seg_tail,
            threshold=self.place_info.get_row_place_info(ridx_diff).row_info.threshold
        )

    def _track_to_track(self, in_id: Union[TrackID, TrackType], end_layer: int,
                        start_layer: Optional[int] = None, wire_name: str = 'sig',
                        mode: RoundMode = RoundMode.NEAREST) -> Union[TrackID, TrackType]:
        '''
        Returns equivalent track on end_layer that is closest to the given track.
        Returned object will be the same type as the given in_tid.
        '''
        is_tid = isinstance(in_id, TrackID)
        if not is_tid:
            assert start_layer is not None, "Must specify start_layer if in_tid is TrackType."
            in_tidx = in_id
        else:
            in_tidx = in_id.base_index
            start_layer = in_id.layer_id
        track_coord = self.grid.track_to_coord(start_layer, in_tidx)
        out_tidx = self.grid.coord_to_track(end_layer, track_coord, mode=mode)
        return TrackID(end_layer, out_tidx,
                       width=self.tr_manager.get_width(end_layer, wire_name)) if is_tid else out_tidx