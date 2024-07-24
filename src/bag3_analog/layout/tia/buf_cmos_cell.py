## SPDX-License-Identifier: BSD-3-Clause AND Apache-2.0
# Copyright 2018 Regents of the University of California
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
"""This module contains layout generators for pseudo differential inverters."""

from typing import Any, Dict, Type, Optional, List, Sequence

from pybag.enum import MinLenMode, RoundMode

from bag.typing import TrackType
from bag.util.immutable import Param
from bag.layout.template import TemplateDB
from bag.layout.routing.base import TrackID, WireArray
from bag.design.module import Module

from xbase.layout.enum import MOSWireType, SubPortMode
from xbase.layout.mos.base import MOSBasePlaceInfo, MOSBase
from xbase.layout.mos.guardring import GuardRing

from bag3_digital.layout.stdcells.gates import InvCore

from bag.layout.enum import DrawTaps
from ...schematic.buf_cmos_cell import bag3_analog__buf_cmos_cell

from .util import max_conn_wires


class BufCMOS(MOSBase):
    """The core of the pseudo differential inverters
    """

    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        MOSBase.__init__(self, temp_db, params, **kwargs)

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__buf_cmos_cell

    @classmethod
    def get_params_info(cls) -> Dict[str, str]:
        return dict(
            pinfo='The MOSBasePlaceInfo object.',
            seg_p='segments of pmos',
            seg_n='segments of nmos',
            w_p='pmos width.',
            w_n='nmos width.',
            ridx_p='pmos row index.',
            ridx_n='nmos row index.',
            show_pins='True to show pins',
            flip_tile='True to flip all tiles',
            draw_taps='LEFT or RIGHT or BOTH or NONE',
            sig_locs='Signal locations for top horizontal metal layer pins',
            ndum='number of dummy at one side, need even number'
        )

    @classmethod
    def get_default_param_values(cls) -> Dict[str, Any]:
        return dict(
            seg_p=-1,
            seg_n=-1,
            w_p=0,
            w_n=0,
            ridx_p=-1,
            ridx_n=0,
            show_pins=False,
            flip_tile=False,
            draw_taps='NONE',
            sig_locs={},
            ndum=0,
        )

    def draw_layout(self) -> None:
        pinfo = MOSBasePlaceInfo.make_place_info(self.grid, self.params['pinfo'])
        self.draw_base(pinfo, flip_tile=self.params['flip_tile'])

        seg_p: int = self.params['seg_p']
        seg_n: int = self.params['seg_n']
        ridx_p: int = self.params['ridx_p']
        ridx_n: int = self.params['ridx_n']
        ndum: int = self.params['ndum']
        draw_taps: DrawTaps = DrawTaps[self.params['draw_taps']]
        sig_locs: Dict[str, TrackType] = self.params['sig_locs']

        for val in [seg_p, seg_n, ndum]:
            if val % 2:
                raise ValueError(f'This generator does not support odd number of segments ')

        tr_manager = self.tr_manager
        hm_layer = self.conn_layer + 1
        vm_layer = hm_layer + 1
        xm_layer = vm_layer + 1

        inv_params = self.params.copy(append=dict(is_guarded=True, show_pins=False, vertical_out=False))
        inv_master = self.new_template(InvCore, params=inv_params)
        inv_ncol = inv_master.num_cols

        # taps
        sub_sep = self.sub_sep_col + 2
        sup_info = self.get_supply_column_info(xm_layer)
        num_taps = 0
        tap_offset = 0
        tap_left = tap_right = False
        if draw_taps in DrawTaps.RIGHT | DrawTaps.BOTH:
            num_taps += 1
            tap_right = True
        if draw_taps in DrawTaps.LEFT | DrawTaps.BOTH:
            num_taps += 1
            tap_offset += sup_info.ncol + sub_sep // 2
            tap_left = True

        # set total number of columns
        # Total width can be limited by either transistor size or by vertical metal size
        seg_max = 2 * max(seg_p, seg_n)
        seg_tot = seg_max + (sup_info.ncol + sub_sep // 2) * num_taps + 2 * ndum


        # --- Placement --- #
        cur_col = tap_offset
        if ndum > 0:
            nmos_dum_p = self.add_mos(ridx_n, cur_col, ndum, tile_idx=0)
            pmos_dum_p = self.add_mos(ridx_p, cur_col, ndum, tile_idx=0)
            cur_col += ndum
        inst_p = self.add_tile(inv_master, 0, cur_col)
        cur_col += 2 * inv_ncol
        mid_idx = self.arr_info.col_to_track(vm_layer, cur_col - inv_ncol, mode=RoundMode.NEAREST)
        inst_n = self.add_tile(inv_master, 0, cur_col, flip_lr=True)
        if ndum > 0:
            cur_col += ndum
            nmos_dum_n = self.add_mos(ridx_n, cur_col, ndum, tile_idx=0, flip_lr=True)
            pmos_dum_n = self.add_mos(ridx_p, cur_col, ndum, tile_idx=0, flip_lr=True)
        # add taps
        lay_range = range(self.conn_layer, xm_layer + 1)
        vdd_table: Dict[int, List[WireArray]] = {lay: [] for lay in lay_range}
        vss_table: Dict[int, List[WireArray]] = {lay: [] for lay in lay_range}
        if tap_left:
            self.add_supply_column(sup_info, 0, vdd_table, vss_table)
        if tap_right:
            self.add_supply_column(sup_info, seg_tot, vdd_table, vss_table, flip_lr=True)
        self.set_mos_size()

        # --- Routing --- #
        # 1. supplies
        vdd_table[hm_layer].append(inst_p.get_pin('VDD', layer=hm_layer))
        vdd_table[hm_layer].append(inst_n.get_pin('VDD', layer=hm_layer))
        self.add_pin('VDD_conn', vdd_table[self.conn_layer], hide=True)
        self.add_pin('VDD_hm', vdd_table[hm_layer], hide=True)
        self.add_pin('VDD_vm', vdd_table[vm_layer], hide=True)
        self.add_pin('VDDA', self.connect_wires(vdd_table[xm_layer]))

        vss_table[hm_layer].append(inst_p.get_pin('VSS', layer=hm_layer))
        vss_table[hm_layer].append(inst_n.get_pin('VSS', layer=hm_layer))
        self.add_pin('VSS_conn', vss_table[self.conn_layer], hide=True)
        self.add_pin('VSS_hm', vss_table[hm_layer], hide=True)
        self.add_pin('VSS_vm', vss_table[vm_layer], hide=True)
        self.add_pin('VSS', self.connect_wires(vss_table[xm_layer]))

        vdd = self.connect_wires(vdd_table[hm_layer])[0]
        vss = self.connect_wires(vss_table[hm_layer])[0]
        tr_w_h = self.tr_manager.get_width(hm_layer, 'sig')
        tr_w_v = self.tr_manager.get_width(vm_layer, 'sig')
        if ndum > 0:
            # connect dummy
            pmos_port, nmos_port = [], []
            for pmos, nmos in zip([pmos_dum_n, pmos_dum_p], [nmos_dum_n, nmos_dum_p]):
                pmos_port += [pmos.s]
                nmos_port += [nmos.s]
            self.connect_to_track_wires(pmos_port, vdd)
            self.connect_to_track_wires(nmos_port, vss)
            # connect g&d to VDD/VSS with M3
            nout_tidx = sig_locs.get('nout', self.get_track_index(ridx_n, MOSWireType.DS_GATE,
                                                                  wire_name='sig', wire_idx=-1))
            pout_tidx = sig_locs.get('pout', self.get_track_index(ridx_p, MOSWireType.DS_GATE,
                                                                  wire_name='sig', wire_idx=0))
            nout_tid = TrackID(hm_layer, nout_tidx, tr_w_h)
            pout_tid = TrackID(hm_layer, pout_tidx, tr_w_h)
            # left (p)
            pmos_p_hm = self.connect_to_tracks([pmos_dum_p.g, pmos_dum_p.d], pout_tid, min_len_mode=MinLenMode.LOWER)
            nmos_p_hm = self.connect_to_tracks([nmos_dum_p.g, nmos_dum_p.d], nout_tid, min_len_mode=MinLenMode.LOWER)
            tidx_p_vm = self.grid.coord_to_track(vm_layer, pmos_p_hm.lower, mode=RoundMode.NEAREST)
            self.connect_to_tracks([pmos_p_hm, vdd], TrackID(vm_layer, tidx_p_vm, width=tr_w_v))
            self.connect_to_tracks([nmos_p_hm, vss], TrackID(vm_layer, tidx_p_vm, width=tr_w_v))
            pmos_n_hm = self.connect_to_tracks([pmos_dum_n.g, pmos_dum_n.d], pout_tid, min_len_mode=MinLenMode.UPPER)
            nmos_n_hm = self.connect_to_tracks([nmos_dum_n.g, nmos_dum_n.d], nout_tid, min_len_mode=MinLenMode.UPPER)
            tidx_n_vm = self.grid.coord_to_track(vm_layer, pmos_n_hm.upper, mode=RoundMode.NEAREST)
            self.connect_to_tracks([pmos_n_hm, vdd], TrackID(vm_layer, tidx_n_vm, width=tr_w_v))
            self.connect_to_tracks([nmos_n_hm, vss], TrackID(vm_layer, tidx_n_vm, width=tr_w_v))

        # 2. export inp, inn
        inp_vm = inst_p.get_pin('in')
        inn_vm = inst_n.get_pin('in')
        self.add_pin('vip', inp_vm)
        self.add_pin('vin', inn_vm)

        # 3. export von, vop and connect to multiple wires on vm_layer
        von_upper_idx = tr_manager.get_next_track(vm_layer, mid_idx, 'sig', 'sig', up=False)
        von_upper = self.grid.track_to_coord(vm_layer, von_upper_idx)

        von_hm = inst_p.get_all_port_pins('out')
        von_lower_idx = tr_manager.get_next_track(vm_layer, inp_vm.track_id.base_index, 'sig', 'sig', up=True)
        von_lower = self.grid.track_to_coord(vm_layer, von_lower_idx)
        von_vm_idx =  tr_manager.get_next_track(vm_layer, inp_vm.track_id.base_index, 'sig', 'sig', up=False)
        try: von_vm = max_conn_wires(self, tr_manager, 'sig', von_hm, start_coord=von_lower, end_coord=von_upper)
        except: von_vm = self.connect_to_tracks(von_hm, TrackID(vm_layer, von_vm_idx, width=tr_w_v))
        vop_upper_idx = tr_manager.get_next_track(vm_layer, inn_vm.track_id.base_index, 'sig', 'sig', up=False)
        vop_upper = self.grid.track_to_coord(vm_layer, vop_upper_idx)
        vop_lower_idx = tr_manager.get_next_track(vm_layer, mid_idx, 'sig', 'sig', up=True)
        vop_lower = self.grid.track_to_coord(vm_layer, vop_lower_idx)
        vop_hm = inst_n.get_all_port_pins('out')
        vop_vm_idx = tr_manager.get_next_track(vm_layer, inn_vm.track_id.base_index, 'sig', 'sig', up=True)
        try: vop_vm = max_conn_wires(self, tr_manager, 'sig', vop_hm, start_coord=vop_lower, end_coord=vop_upper)
        except:  vop_vm = self.connect_to_tracks(vop_hm, TrackID(vm_layer, vop_vm_idx, width=tr_w_v))

        self.add_pin('von', von_vm)
        self.add_pin('vop', vop_vm)
        sch_params = inv_master.sch_params
        w_n = sch_params['w_n']
        w_p = sch_params['w_p']
        lch = sch_params['lch']
        if ndum > 0:
            dum_info = [(('nch', w_n, lch, sch_params['th_n'], 'VSS', 'VSS'), ndum * 2),
                        (('pch', w_p, lch, sch_params['th_p'], 'VDDA', 'VDDA'), ndum * 2)]
            sch_params = sch_params.copy(append=dict(dum_info=dum_info))
        # set





        self.sch_params = sch_params


class BufCMOSRow(MOSBase):
    """The core of the pseudo differential inverters
    """

    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        MOSBase.__init__(self, temp_db, params, **kwargs)

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__buf_cmos_cell

    @classmethod
    def get_params_info(cls) -> Dict[str, str]:
        return dict(
            pinfo='The MOSBasePlaceInfo object.',
            seg_p='segments of pmos',
            seg_n='segments of nmos',
            w_p='pmos width.',
            w_n='nmos width.',
            ridx_p='pmos row index.',
            ridx_n='nmos row index.',
            show_pins='True to show pins',
            flip_tile='True to flip all tiles',
            sig_locs='Signal locations for top horizontal metal layer pins',
            ndum='number of dummy at one side, need even number'
        )

    @classmethod
    def get_default_param_values(cls) -> Dict[str, Any]:
        return dict(
            seg_p=-1,
            seg_n=-1,
            w_p=0,
            w_n=0,
            ridx_p=-1,
            ridx_n=0,
            show_pins=False,
            flip_tile=False,
            sig_locs={},
            ndum=0,
        )

    def draw_layout(self) -> None:
        pinfo = MOSBasePlaceInfo.make_place_info(self.grid, self.params['pinfo'])
        self.draw_base(pinfo, flip_tile=self.params['flip_tile'])

        # core_tile
        _pinfo = self.get_tile_pinfo(tile_idx=1)

        seg_p: int = self.params['seg_p']
        seg_n: int = self.params['seg_n']
        w_p: int = self.params['w_p']
        w_n: int = self.params['w_n']
        ridx_p: int = self.params['ridx_p']
        ridx_n: int = self.params['ridx_n']
        ndum: int = self.params['ndum']
        sig_locs: Dict[str, TrackType] = self.params['sig_locs']

        for val in (seg_p, seg_n, ndum):
            if val % 2:
                raise ValueError(f'This generator does not support odd number of segments ')

        hm_layer = self.conn_layer + 1
        vm_layer = hm_layer + 1
        xm_layer = vm_layer + 1

        inv_params = self.params.copy(append=dict(is_guarded=True, show_pins=False, vertical_sup=True,
                                                  vertical_out=False),
                                      remove=['pinfo'])
        inv_master = self.new_template(InvCore, params=dict(pinfo=_pinfo, **inv_params))
        inv_ncol = inv_master.num_cols

        # set total number of columns
        seg_max = 2 * max(seg_p, seg_n)
        seg_tot = seg_max + 2 * ndum

        # taps
        sub_vss = self.add_substrate_contact(0, 0, tile_idx=0, seg=seg_tot, port_mode=SubPortMode.BOTH)
        sub_vdd = self.add_substrate_contact(0, 0, tile_idx=2, seg=seg_tot, port_mode=SubPortMode.BOTH)

        # --- Placement --- #
        cur_col = 0
        if ndum > 0:
            nmos_dum_p = self.add_mos(ridx_n, cur_col, ndum, tile_idx=1, w=w_n)
            pmos_dum_p = self.add_mos(ridx_p, cur_col, ndum, tile_idx=1, w=w_p)
            cur_col += ndum
        inst_p = self.add_tile(inv_master, 1, cur_col)
        cur_col += 2 * inv_ncol
        mid_idx = self.arr_info.col_to_track(vm_layer, cur_col - inv_ncol, mode=RoundMode.NEAREST)
        inst_n = self.add_tile(inv_master, 1, cur_col, flip_lr=True)
        if ndum > 0:
            cur_col += ndum
            nmos_dum_n = self.add_mos(ridx_n, cur_col, ndum, tile_idx=1, flip_lr=True, w=w_n)
            pmos_dum_n = self.add_mos(ridx_p, cur_col, ndum, tile_idx=1, flip_lr=True, w=w_p)

        # set size
        self.set_mos_size()

        # --- Routing --- #
        tr_manager = self.tr_manager
        hm_layer = self.conn_layer + 1
        # 1. supplies
        vdd_tidx = self.get_track_index(0, MOSWireType.DS, wire_name='sup', wire_idx=-1, tile_idx=2)
        vss_tidx = self.get_track_index(0, MOSWireType.DS, wire_name='sup', wire_idx=-1, tile_idx=0)
        w_sup_hm = tr_manager.get_width(hm_layer, 'sup')

        inst_vss, inst_vdd = [sub_vss], [sub_vdd]
        for inst in (inst_p, inst_n):
            inst_vss.extend(inst.get_all_port_pins('VSS', layer=self.conn_layer))
            inst_vdd.extend(inst.get_all_port_pins('VDD', layer=self.conn_layer))
        if ndum > 0:
            # connect dummy
            for pmos, nmos in zip([pmos_dum_n, pmos_dum_p], [nmos_dum_n, nmos_dum_p]):
                inst_vdd.extend([pmos.g, pmos.d, pmos.s])
                inst_vss.extend([nmos.g, nmos.d, nmos.s])
        self.connect_wires(inst_vss)
        self.connect_wires(inst_vdd)
        vss = self.connect_to_tracks([sub_vss[0::2]], TrackID(hm_layer, vss_tidx, width=w_sup_hm), min_len_mode=MinLenMode.MIDDLE)
        vdd = self.connect_to_tracks([sub_vdd[0::2]], TrackID(hm_layer, vdd_tidx, width=w_sup_hm), min_len_mode=MinLenMode.MIDDLE)
        self.add_pin('VDDA', vdd, connect=True)
        self.add_pin('VSS', vss, connect=True)

        # 2. export inp, inn
        inp_vm = inst_p.get_pin('in')
        inn_vm = inst_n.get_pin('in')
        self.add_pin('vip', inp_vm)
        self.add_pin('vin', inn_vm)

        # 3. export von, vop and connect to multiple wires on vm_layer
        # mid_idx = self.grid.coord_to_track(vm_layer, inst_p.bound_box.xh, mode=RoundMode.NEAREST)
        von_upper_idx = tr_manager.get_next_track(vm_layer, mid_idx, 'sig', 'sig', up=False)
        von_upper = self.grid.track_to_coord(vm_layer, von_upper_idx)
        vop_lower_idx = tr_manager.get_next_track(vm_layer, mid_idx, 'sig', 'sig', up=True)
        vop_lower = self.grid.track_to_coord(vm_layer, vop_lower_idx)
        von_hm = inst_p.get_all_port_pins('out')
        von_lower_idx = tr_manager.get_next_track(vm_layer, inp_vm.track_id.base_index, 'sig', 'sig', up=True)
        von_lower = self.grid.track_to_coord(vm_layer, von_lower_idx)
        von_vm = max_conn_wires(self, tr_manager, 'sig', von_hm, start_coord=von_lower, end_coord=von_upper)
        vop_upper_idx = tr_manager.get_next_track(vm_layer, inn_vm.track_id.base_index, 'sig', 'sig', up=False)
        vop_upper = self.grid.track_to_coord(vm_layer, vop_upper_idx)
        vop_hm = inst_n.get_all_port_pins('out')
        vop_vm = max_conn_wires(self, tr_manager, 'sig', vop_hm, start_coord=vop_lower, end_coord=vop_upper)

        self.add_pin('von', von_vm)
        self.add_pin('vop', vop_vm)
        sch_params = dict(**inv_master.sch_params)
        lch = sch_params['lch']
        if ndum > 0:
            dum_info = [(('nch', sch_params['w_n'], lch, sch_params['th_n'], 'VSS', 'VSS'), ndum * 2),
                        (('pch', sch_params['w_p'], lch, sch_params['th_p'], 'VDDA', 'VDDA'), ndum * 2)]
            sch_params['dum_info'] = dum_info
        # set properties
        self.sch_params = sch_params


class BufCMOSGR(GuardRing):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        GuardRing.__init__(self, temp_db, params, **kwargs)

    @classmethod
    def get_params_info(cls) -> Dict[str, str]:
        ans = BufCMOS.get_params_info()
        ans.update(
            pmos_gr='pmos guard ring tile name.',
            nmos_gr='nmos guard ring tile name.',
            edge_ncol='Number of columns on guard ring edge.  Use 0 for default.',
        )
        return ans

    @classmethod
    def get_default_param_values(cls) -> Dict[str, Any]:
        ans = BufCMOSV1.get_default_param_values()
        ans.update(
            pmos_gr='pgr',
            nmos_gr='ngr',
            edge_ncol=0,
        )
        return ans

    def get_layout_basename(self) -> str:
        return self.__class__.__name__

    def draw_layout(self) -> None:
        params = self.params
        pmos_gr: str = params['pmos_gr']
        nmos_gr: str = params['nmos_gr']
        edge_ncol: int = params['edge_ncol']

        core_params = params.copy(remove=['pmos_gr', 'nmos_gr', 'edge_ncol'])
        master = self.new_template(BufCMOSV1, params=core_params)

        sub_sep = master.sub_sep_col
        gr_sub_sep = master.gr_sub_sep_col
        sep_ncol_left = sep_ncol_right = sub_sep
        draw_taps: DrawTaps = DrawTaps[params['draw_taps']]
        if draw_taps in DrawTaps.RIGHT | DrawTaps.BOTH:
            sep_ncol_right = gr_sub_sep - sub_sep // 2
        if draw_taps in DrawTaps.LEFT | DrawTaps.BOTH:
            sep_ncol_left = gr_sub_sep - sub_sep // 2
        sep_ncol = (sep_ncol_left, sep_ncol_right)

        inst, sup_list = self.draw_guard_ring(master, pmos_gr, nmos_gr, sep_ncol, edge_ncol)
        vdd_hm_list, vss_hm_list = [], []
        for (vss_list, vdd_list) in sup_list:
            vss_hm_list.extend(vss_list)
            vdd_hm_list.extend(vdd_list)

        self.connect_to_track_wires(vss_hm_list, inst.get_all_port_pins('VSS_vm'))
        self.connect_to_track_wires(vdd_hm_list, inst.get_all_port_pins('VDD_vm'))


class BufCMOSRowGR(GuardRing):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        GuardRing.__init__(self, temp_db, params, **kwargs)

    @classmethod
    def get_params_info(cls) -> Dict[str, str]:
        ans = BufCMOSV1Row.get_params_info()
        ans.update(
            pmos_gr='pmos guard ring tile name.',
            nmos_gr='nmos guard ring tile name.',
            edge_ncol='Number of columns on guard ring edge.  Use 0 for default.',
        )
        return ans

    @classmethod
    def get_default_param_values(cls) -> Dict[str, Any]:
        ans = BufCMOSV1Row.get_default_param_values()
        ans.update(
            pmos_gr='pgr',
            nmos_gr='ngr',
            edge_ncol=0,
        )
        return ans

    def get_layout_basename(self) -> str:
        return self.__class__.__name__

    def draw_layout(self) -> None:
        params = self.params
        pmos_gr: str = params['pmos_gr']
        nmos_gr: str = params['nmos_gr']
        edge_ncol: int = params['edge_ncol']

        core_params = params.copy(remove=['pmos_gr', 'nmos_gr', 'edge_ncol'])
        master = self.new_template(BufCMOSV1Row, params=core_params)

        gr_sub_sep = master.gr_sub_sep_col
        sep_ncol_left = sep_ncol_right = gr_sub_sep
        sep_ncol = (sep_ncol_left, sep_ncol_right)

        inst, sup_list = self.draw_guard_ring(master, pmos_gr, nmos_gr, sep_ncol, edge_ncol)
        vdd_hm_list, vss_hm_list = [], []
        for (vss_list, vdd_list) in sup_list:
            vss_hm_list.extend(vss_list)
            vdd_hm_list.extend(vdd_list)

        self.add_pin('VSS', vss_hm_list, connect=True)
        self.add_pin('VDDA', vdd_hm_list, connect=True)
