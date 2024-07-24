"""This module defines delay_res_unit."""

from typing import Mapping, Any, Optional, Type, cast, Dict

from bag.util.immutable import Param
from bag.design.module import Module
from bag.design.database import ModuleDB
from bag.layout.template import TemplateDB, TemplateBase
from bag.layout.routing.base import TrackID, WireArray

from pybag.enum import RoundMode, Orientation, Direction
from pybag.core import Transform, BBox

from xbase.layout.res.base import ResBasePlaceInfo, ResArrayBase
from xbase.layout.mos.top import GenericWrapper
from xbase.layout.array.top import ArrayBaseWrapper
from xbase.layout.cap.core import MOMCapCore
from bag3_analog.layout.res.termination import Termination
from .buf_cmos_cell import BufCMOSGR, BufCMOS
from ...schematic.tia_res import bag3_analog__tia_res

import numpy as np
from .util import round_to_blk_pitch, draw_stack_wire, extend_matching_wires

class TIARes(ResArrayBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        ResArrayBase.__init__(self, temp_db, params, **kwargs)

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__tia_res

    @classmethod
    def get_params_info(cls) -> Mapping[str, str]:
        return dict(
            pinfo='The ResBasePlaceInfo object.',
            nx_dum='Number of dummies on each side, X direction',
            ny_dum='Number of dummies on each side, Y direction',
        )

    @classmethod
    def get_default_param_values(cls) -> Mapping[str, Any]:
        return dict(nx_dum=0, ny_dum=0)

    def draw_layout(self) -> None:
        pinfo = cast(ResBasePlaceInfo, ResBasePlaceInfo.make_place_info(self.grid, self.params['pinfo']))
        self.draw_base(pinfo)

        sub_type = pinfo.res_config['sub_type_default']
        if sub_type != 'ntap':
            raise ValueError(f'This generator does not support sub_type={sub_type}. Only ntap is supported.')

        # Get hm_layer and vm_layer WireArrays
        warrs, bulk_warrs = self.connect_hm_vm()

        # Connect all dummies
        self.connect_dummies(warrs, bulk_warrs)

        # Supply connections on xm_layer
        self.connect_bulk_xm(bulk_warrs)

        unit_params = dict(
            w=pinfo.w_res,
            l=pinfo.l_res,
            intent=pinfo.res_type,
        )
        nx, ny = pinfo.nx, pinfo.ny
        nx_dum: int = self.params['nx_dum']
        ny_dum: int = self.params['ny_dum']
        npar = nx - 2 * nx_dum
        nser = ny - 2 * ny_dum
        num_dum = nx * ny - npar * nser

        # --- Routing of unit resistors --- #
        hm_layer = self.conn_layer + 1
        vm_layer = hm_layer + 1
        xm_layer = vm_layer + 1
        r_bot, r_top = self.connect_units(warrs, nx_dum,  nx - nx_dum, ny_dum, ny - ny_dum)

        # connect top vm_layers to xm_layer
        w_xm_sig = self.tr_manager.get_width(xm_layer, 'sig')
        xm_idx0 = self.grid.coord_to_track(xm_layer, r_top.middle, RoundMode.NEAREST)
        xm_tid0 = TrackID(xm_layer, xm_idx0, w_xm_sig)
        xm_idx1 = self.grid.coord_to_track(xm_layer, r_bot.middle, RoundMode.NEAREST)
        xm_tid1 = TrackID(xm_layer, xm_idx1, w_xm_sig)
        self.add_pin('PLUS', self.connect_to_tracks(r_top, xm_tid0))
        self.add_pin('MINUS', self.connect_to_tracks(r_bot, xm_tid1))

        self.sch_params = dict(
            res_params=dict(
                unit_params=unit_params,
                nser=nser,
                npar=npar,
            ),
            dum_params=dict(
                unit_params=unit_params,
                nser=1,
                npar=num_dum,
            ),
            sub_type=sub_type,
        )


class TIA(TemplateBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        TemplateBase.__init__(self, temp_db, params, **kwargs)
        self._sup_wire = {}
        self._decap_w = 0

    @property
    def sup_wire(self) -> Dict[WireArray, Any]:
        return self._sup_wire

    @property
    def decap_w(self) -> int:
        return self._decap_w

    def get_schematic_class_inst(self) -> Optional[Type[Module]]:
        if self.params['res_term_params']:
            # noinspection PyTypeChecker
            return ModuleDB.get_schematic_class('bag3_analog', 'tia_term')
        else:
            # noinspection PyTypeChecker
            return ModuleDB.get_schematic_class('bag3_analog', 'tia')


    @classmethod
    def get_params_info(cls) -> Mapping[str, str]:
        return dict(
            buf_params='Parameters for buffer',
            res_params='Parameters for feedback resistor',
            cap_params='Parameters for mom cap, if not specified, removed the mom cap',
            res_term_params='Parameters for termination resistor',
            decap_params='Parameters for DC decoupling cap',
            do_power_fill='True to do power fill from M4 to M6',
            guard_ring='True to draw guard ring',
        )

    @classmethod
    def get_default_param_values(cls) -> Dict[str, Any]:
        return dict(
            do_power_fill=False,
            cap_params=None,
            res_term_params=None,
            decap_params=None,
            guard_ring=True,
        )

    def draw_layout(self) -> None:
        do_power_fill = self.params['do_power_fill']
        # make masters
        buf_params: Mapping[str, Any] = self.params['buf_params']
        guard_ring: bool = self.params['guard_ring']

        buf_gen = BufCMOSGR if guard_ring else BufCMOS
        buf_master = self.new_template(GenericWrapper, params=dict(cls_name=buf_gen.get_qualified_name(),
                                                                   params=buf_params))

        res_params: Mapping[str, Any] = self.params['res_params']
        res_master = self.new_template(ArrayBaseWrapper, params=dict(cls_name=TIARes.get_qualified_name(),
                                                                     params=res_params))

        cap_params: Optional[Mapping[str, Any]] = self.params.get('cap_params', None)
        if cap_params:
            cap_master = self.new_template(MOMCapCore, params=cap_params)

        res_term_params: Optional[Mapping[str, Any]] = self.params.get('res_term_params', None)
        if res_term_params:
            res_term_master = self.new_template(ArrayBaseWrapper, params=dict(cls_name=Termination.get_qualified_name(),
                                                                     params=res_term_params))

        decap_params: Optional[Mapping[str, Any]] = self.params.get('decap_params', None)
        if decap_params:
            decap_master = self.new_template(MOMCapCore, params=decap_params)

        # --- Placement --- #
        w_blk, h_blk = self.grid.get_block_size(buf_master.size[0])
        buf_w, buf_h = buf_master.bound_box.w, buf_master.bound_box.h
        res_w, res_h = res_master.bound_box.w, res_master.bound_box.h
        if cap_params:
            cap_w, cap_h = cap_master.bound_box.w, cap_master.bound_box.h
        else:
            cap_w, cap_h = 0, 0

        if res_term_params:
            res_term_w, res_term_h = res_term_master.bound_box.w, res_term_master.bound_box.h
        else:
            res_term_w, res_term_h = 0, 0

        if decap_params:
            decap_w, decap_h = decap_master.bound_box.w, decap_master.bound_box.h
        else:
            decap_w, decap_h = 0, 0

        self._decap_w = decap_w

        tot_w = max(buf_w + 2 * res_w, 2 * cap_w + res_term_w) + decap_w
        tot_h = max(cap_h + max(buf_h, res_h) + res_term_h, decap_h)

        buf_xl = (tot_w - buf_w + decap_w) // 2
        buf_yl = cap_h + res_term_h
        buf_xl, buf_yl = round_to_blk_pitch(buf_xl, buf_yl, w_blk, h_blk)
        buf_inst = self.add_instance(buf_master, xform=Transform(dx=buf_xl, dy=buf_yl))
        tr_manager = buf_master.core.tr_manager

        res_xl = buf_xl - res_w
        res_yl = cap_h + (max(buf_h, res_h) - res_h) // 2 + res_term_h
        res_xl, res_yl = round_to_blk_pitch(res_xl, res_yl, w_blk, h_blk)
        resp_inst = self.add_instance(res_master, xform=Transform(dx=res_xl, dy=res_yl))
        resn_inst = self.add_instance(res_master, xform=Transform(dx=res_xl + res_w + buf_w, dy=res_yl))

        if cap_params:
            cap_xl = (tot_w - 2 * cap_w + decap_w) // 2
            cap_yh = cap_h
            cap_xl, cap_yh = round_to_blk_pitch(cap_xl, cap_yh, w_blk, h_blk)
            capp_inst = self.add_instance(cap_master, xform=Transform(dx=cap_xl + cap_w, dy=cap_yh, mode=Orientation.R180))
            capn_inst = self.add_instance(cap_master, xform=Transform(dx=cap_xl + cap_w, dy=cap_yh, mode=Orientation.MX))

        if res_term_params:
            res_term_xl = (tot_w - res_term_w + decap_w) // 2
            res_term_yl = 0
            res_term_xl, res_term_yl = round_to_blk_pitch(res_term_xl, res_term_yl, w_blk, h_blk)
            res_term_inst = self.add_instance(res_term_master, xform=Transform(dx=res_term_xl, dy=res_term_yl))

        if decap_params:
            decap_xl = decap_w
            decap_yl = 0
            decap_xl, decap_yl = round_to_blk_pitch(decap_xl, decap_yl, w_blk, h_blk)
            decap_inst = self.add_instance(decap_master, xform=Transform(dx=decap_xl, dy=decap_yl, mode=Orientation.MY),)

        # # --- Routing --- #
        xm_layer = resp_inst.get_pin('MINUS').layer_id
        ym_layer = xm_layer + 1
        zm_layer = ym_layer + 1
        w_sig_xm = tr_manager.get_width(xm_layer, 'sig')
        w_sig_ym = tr_manager.get_width(ym_layer, 'sig')

        # vip/ vin
        if cap_params:
            self.reexport(capp_inst.get_port('minus'), net_name='vip')
            self.reexport(capn_inst.get_port('minus'), net_name='vin')
        if res_term_params:
            # export to zm_layer
            stack = draw_stack_wire(self, res_term_inst.get_pin('PLUS'), zm_layer, tr_list=[1, 4], sp_list=[3, 4])
            vip_zm = stack[-1]
            stack = draw_stack_wire(self, res_term_inst.get_pin('MINUS'), zm_layer, tr_list=[1, 4], sp_list=[3, 4])
            vin_zm = stack[-1]
            stack = draw_stack_wire(self, res_term_inst.get_pin('MID'), zm_layer, tr_list=[1, 4], sp_list=[3, 4])
            mid_zm = stack[-1]
            vdd_res = res_term_inst.get_all_port_pins('VDD', xm_layer)
            vdd_zm = []
            for vdd in vdd_res:
                stack = draw_stack_wire(self, vdd, zm_layer, tr_list=[1, 4], sp_list=[3, 4])
                vdd_zm += stack[-1]

            self.add_pin('VDD', vdd_zm, connect=True)
            # mid
            mid_xm = [res_term_inst.get_pin('MID')]
            if decap_params:
                mid_ym_tidx = decap_inst.get_pin('plus', layer=ym_layer).track_id.base_index
                mid_ym_tidx = tr_manager.get_next_track(ym_layer, mid_ym_tidx, 'sig', 'sig')
                mid_ym_tidx = tr_manager.get_next_track(ym_layer, mid_ym_tidx, 'sig', 'sig')
                mid_ym_tidx = tr_manager.get_next_track(ym_layer, mid_ym_tidx, 'sig', 'sig')
                mid_xm += decap_inst.get_all_port_pins('plus', xm_layer)
                self.connect_to_tracks(mid_xm + mid_zm, TrackID(ym_layer, mid_ym_tidx, width=w_sig_ym))
                self.add_pin('VDD', decap_inst.get_all_port_pins('minus', zm_layer), connect=True)

        # vip_m/ vin_m

        vlay = (buf_inst.get_port('vip').get_single_layer(), 'drawing')
        vdir = Direction.LOWER
        vip_m_buf = buf_inst.get_pin('vip')
        vin_m_buf = buf_inst.get_pin('vin')
        vip_m_res = resp_inst.get_pin('MINUS')
        vin_m_res = resn_inst.get_pin('MINUS')

        vm_layer = xm_layer - 1
        ym_layer = xm_layer + 1
        vip_passive =[vip_m_res]
        vin_passive =[vin_m_res]
        if cap_params:
            vip_m_cap_xm, vip_m_cap_vm, vip_m_cap_ym = capp_inst.get_all_port_pins('plus', xm_layer)[0], \
                                                       capp_inst.get_all_port_pins('plus', vm_layer)[0],\
                                                       capp_inst.get_all_port_pins('plus', ym_layer)[0]
            vin_m_cap_xm, vin_m_cap_vm, vin_m_cap_ym = capn_inst.get_all_port_pins('plus', xm_layer)[0], \
                                         capn_inst.get_all_port_pins('plus', vm_layer)[0], \
                                         capn_inst.get_all_port_pins('plus', ym_layer)[0]

            vip_xm_idx = tr_manager.get_next_track(xm_layer, vip_m_cap_xm.track_id.base_index, 'sig', 'sig', up=True)
            vip_xm_idx = tr_manager.get_next_track(xm_layer, vip_xm_idx, 'sig', 'sig', up=True)
            vin_xm_idx = tr_manager.get_next_track(xm_layer, vin_m_cap_xm.track_id.base_index, 'sig', 'sig', up=True)
            vin_xm_idx = tr_manager.get_next_track(xm_layer, vin_xm_idx, 'sig', 'sig', up=True)
            vip_m_cap = self.connect_to_tracks([vip_m_cap_vm, vip_m_cap_ym], TrackID(xm_layer, vip_xm_idx, width=w_sig_xm))
            vin_m_cap = self.connect_to_tracks([vin_m_cap_vm, vin_m_cap_ym], TrackID(xm_layer, vin_xm_idx, width=w_sig_xm))
            vip_passive += [vip_m_cap]
            vin_passive += [vin_m_cap]
        vip_m = self.connect_bbox_to_track_wires(vdir, vlay, vip_m_buf, vip_passive)
        vin_m = self.connect_bbox_to_track_wires(vdir, vlay, vin_m_buf, vin_passive)
        vip_name = 'vip_m' if cap_params else 'vip'
        vin_name = 'vin_m' if cap_params else 'vin'


        # connect vip/ vin on M7
        if res_term_params:
            stack_p = draw_stack_wire(self, vip_m[0], zm_layer, tr_list=[1, 4], sp_list=[3, 4])
            stack_n = draw_stack_wire(self, vin_m[0], zm_layer, tr_list=[1, 4], sp_list=[3, 4])
            buf_vip = stack_p[-1]
            buf_vin = stack_n[-1]
            # vip_m7_tidx = self.grid.coord_to_track(zm_layer + 1, buf_vip[0].middle, mode=RoundMode.GREATER)
            # vin_m7_tidx = self.grid.coord_to_track(zm_layer + 1, buf_vin[0].middle, mode=RoundMode.LESS_EQ)
            # vip_m7 = self.connect_to_tracks(buf_vip + vip_zm, TrackID(zm_layer + 1, vip_m7_tidx, width=1))
            # vin_m7 = self.connect_to_tracks(buf_vin + vin_zm, TrackID(zm_layer + 1, vin_m7_tidx, width=1))
            # vip_m7, vin_m7 = extend_matching_wires(self,[vip_m7, vin_m7])
            self.add_pin(vip_name, buf_vip + vip_zm, connect=True)
            self.add_pin(vin_name, buf_vin + vin_zm, connect=True)
        else:
            self.add_pin(vip_name, vip_m)
            self.add_pin(vin_name, vin_m)


        # vop/ von
        vop_m_buf = buf_inst.get_all_port_pins('vop')
        von_m_buf = buf_inst.get_all_port_pins('von')
        vop_m_res = resn_inst.get_pin('PLUS')
        von_m_res = resp_inst.get_pin('PLUS')
        for bbox in vop_m_buf:
            vop = self.connect_bbox_to_track_wires(vdir, vlay, bbox, vop_m_res)
        for bbox in von_m_buf:
            von = self.connect_bbox_to_track_wires(vdir, vlay, bbox, von_m_res)
        self.add_pin('vop', vop_m_res)
        self.add_pin('von', von_m_res)

        # VDD/VSS
        vdd_xm_buf = buf_inst.get_all_port_pins('VDDA')
        vdd_xm_left = resp_inst.get_all_port_pins('VDD')
        vdd_xm_right = resn_inst.get_all_port_pins('VDD')
        vdd_xm = vdd_xm_buf + vdd_xm_left + vdd_xm_right
        vss_xm = buf_inst.get_all_port_pins('VSS')
        top_idx = np.argmax([vdd.track_id.base_index for vdd in vdd_xm])
        sup_xm = vdd_xm + vss_xm
        bot_idx = np.argmin([vdd.track_id.base_index for vdd in sup_xm])
        # self._sup_wire.update(top_wire=vdd_xm[top_idx], bot_wire=sup_xm[bot_idx], left_wire=vdd_xm[1], right_wire=vdd_xm[-1])
        self._sup_wire.update(top_wire=vdd_xm[top_idx], bot_wire=sup_xm[bot_idx])

        # set size
        xm_layer = vdd_xm[0].layer_id
        ym_layer = xm_layer + 1
        zm_layer = ym_layer + 1
        self.set_size_from_bound_box(zm_layer, BBox(0, 0, tot_w, tot_h))

        if not do_power_fill:
            self.add_pin('VDD_xm_buf', vdd_xm_buf, label='VDD:')
            self.add_pin('VDD_xm_right', vdd_xm_right, label='VDD:')
            self.add_pin('VDD_xm_left', vdd_xm_left, label='VDD:')
            self.add_pin('VSS_xm', vss_xm, label='VSS:')
        else:
            sup_w_xm = tr_manager.get_width(xm_layer, 'sup')
            bbox = self.bound_box
            bb_xl, bb_xh, bb_yl, bb_yh = bbox.xl, bbox.xh, bbox.yl, bbox.yh

            # M5
            sup_w_ym = tr_manager.get_width(ym_layer, 'sup')
            wl, wh = self.grid.get_wire_bounds(ym_layer, 0, width=sup_w_ym)
            w_ym = int((wh - wl) / 2)
            via_ext_xm, via_ext_ym = self.grid.get_via_extensions(Direction.LOWER, xm_layer, sup_w_xm, sup_w_ym)
            dx =via_ext_xm + w_ym
            # dy = self.bound_box.yl - vss_xm[0].bound_box.yl + via_ext_ym
            bb = BBox(xl=bb_xl - dx, xh=bb_xh - dx, yl=capp_inst.bound_box.yh, yh=bb_yh + via_ext_ym)
            vdd_ym, vss_ym = self.do_power_fill(ym_layer, tr_manager, vdd_xm, vss_xm, bound_box=bb)
            # self.add_pin('VDD_ym', vdd_ym, label='VDD:')
            # self.add_pin('VSS_ym', vss_ym, label='VSS:')

            # M6
            sup_w_zm = tr_manager.get_width(zm_layer, 'sup')
            wl, wh = self.grid.get_wire_bounds(zm_layer, 0, width=sup_w_zm)
            w_zm = int((wh - wl) / 2)
            via_ext_zm, via_ext_zm_x = self.grid.get_via_extensions(Direction.LOWER, ym_layer, sup_w_ym, sup_w_zm)
            dx = self.bound_box.xl - vss_ym[0].bound_box.xl + via_ext_zm_x
            bb = bb.expand(dy=- via_ext_zm - w_zm, dx=dx)
            vdd_zm, vss_zm = self.do_power_fill(zm_layer, tr_manager, vdd_ym, vss_ym, bound_box=bb)
            self.add_pin('VDD_zm', vdd_zm, label='VDD:')
            self.add_pin('VSS_zm', vss_zm, label='VSS:')

        # set size
        self.set_size_from_bound_box(6, BBox(0, 0, tot_w, tot_h))

        # set schematic parameters
        if res_term_params:
            self.sch_params = dict(
                buf_cmos_cell_params=buf_master.sch_params,
                res_params=res_master.sch_params,
                res_term_params=res_term_master.sch_params,
                decap_params=decap_master.sch_params,

            )
        else:

            self.sch_params = dict(
                buf_cmos_cell_params=buf_master.sch_params,
                res_params=res_master.sch_params,
                cap_params=cap_master.sch_params if cap_params else None,
                with_cap=True if cap_params else False,
            )
