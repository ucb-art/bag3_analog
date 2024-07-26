# -*- coding: utf-8 -*-

"""This module contains layout implementations for several standard cells."""

from typing import Any, Dict, Optional, Union, Tuple, Mapping, Type, List

from bag.typing import CoordType, TrackType

from pybag.enum import MinLenMode, RoundMode, PinMode, LogLevel

from math import log2

from bag.util.math import HalfInt
from bag.util.immutable import Param
from bag.util.logging import LoggingBase
from bag.design.module import Module
from bag.layout.template import TemplateDB
from bag.layout.routing.base import TrackID, WireArray

from xbase.layout.enum import MOSWireType
from xbase.layout.mos.base import MOSBasePlaceInfo, MOSBase

from bag3_analog.schematic.power_pmos import bag3_analog__power_pmos
from bag3_analog.schematic.power_nmos import bag3_analog__power_nmos


class PowerPMOS(MOSBase, LoggingBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        debug = params.get('debug', False)
        LoggingBase.__init__(self, "DCOMatrix",
                             "DCOMatrix.log",
                             log_level=LogLevel.INFO if not debug else LogLevel.DEBUG)
        MOSBase.__init__(self, temp_db, params, **kwargs)
        self.vss_track_list = []
        self.vdd_track_list = []
        self.offset_cols = 0
        self._n = "\n"

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__power_pmos

    @classmethod
    def get_params_info(cls) -> Mapping[str, str]:
        return dict(
            pinfo='The MOSBasePlaceInfo object.',
            rows='[int] Number of rows.',
            seg='[int] number of segments per row.',
            wp='[int] pmos width.',
            lch='[int] channel length.',
            intent='[str] pmos threshold.',
            ridx_p='[int] pmos row index.',
            row_layout_info='[Mapping] Row layout information dictionary.',
            sig_locs='[Mapping] Signal track location dictionary.',
            show_pins='[bool] True to draw pin geometries.',
            debug='[bool] true to print debug statements',
        )

    @classmethod
    def get_default_param_values(cls) -> Mapping[str, Any]:
        return dict(
            wp=None,
            lch=None,
            intent=None,
            ridx_p=-1,
            row_layout_info=None,
            sig_locs=None,
            show_pins=True,
            debug=False,
        )

    def draw_layout(self):
        rows: int = self.params['rows']
        seg: int = self.params['seg']
        ridx_p: int = self.params['ridx_p']
        sig_locs: Dict[str, Tuple[TrackType, TrackType]] = self.params['sig_locs']
        show_pins: bool = self.params['show_pins']
        pinfo_dict: Mapping[str, any] = dict(**self.params['pinfo'])

        wp: int = self.params['wp']
        lch: int = self.params['lch']
        intent: str = self.params['intent']

        device_list, vdd_list, gate_list, source_list, out_list = [], [], [], [], []
        # Adding tap rows consumes some rows, add them back
        total_rows_and_taps = rows + (rows // 2) + 1
        ntap_tiles = range(0, total_rows_and_taps, 3)   # skip tile 0 due to have correct patternwithout replicating taps
        dev_tiles = [tile for tile in range(1, total_rows_and_taps) if tile not in ntap_tiles]

        ntap_tile_dict = dict(name='ntap_tile')
        unit_tile_dict_no_flip = dict(name='unit_tile')
        unit_tile_dict_flip = dict(name='unit_tile', flip=True)

        unit_tile_idx_even = dev_tiles[1::2]
        unit_tile_idx_odd = dev_tiles[::2]

        tile_list = []
        for idx in range(total_rows_and_taps):
            if idx in unit_tile_idx_odd:
                tile_list.append(unit_tile_dict_no_flip)
            elif idx in unit_tile_idx_even:
                tile_list.append(unit_tile_dict_flip)
            else:
                tile_list.append(ntap_tile_dict)

        pinfo_dict['tiles'] = tile_list

        pinfo = MOSBasePlaceInfo.make_place_info(self.grid, pinfo_dict)
        self.draw_base(pinfo)
        self.log(f'Tiles: {self._n + self._n.join([f"{tile} {self.get_tile_pinfo(tile).name} flipped: {bool(pinfo[0].get_tile_info(tile)[-1])}" for tile in range(total_rows_and_taps - 1, -1, -1)])}',
                 level=LogLevel.DEBUG)
        tr_manager = self.tr_manager

        hm_layer = self.conn_layer + 1
        vm_layer = hm_layer + 1

        for tile in ntap_tiles:
            self.log(f'Placing tap row on tile {tile}', level=LogLevel.DEBUG)
            ntap_port = self.add_substrate_contact(0, 0, tile_idx=tile, seg=seg)
            vdd_tid = self.get_track_id(0, MOSWireType.DS, 'sup', wire_idx=0, tile_idx=tile)
            vdd_list.append(self.connect_to_tracks(ntap_port, vdd_tid))
        for row in dev_tiles:
            self.log(f'Adding PMOS on tile {row}', level=LogLevel.DEBUG)
            cur_dev = self.add_mos(ridx_p, 0, seg, tile_idx=row)
            device_list.append(cur_dev)
            # vdd_tid = self.get_track_id(ridx_p, MOSWireType.DS, 'sup', wire_idx=0, tile_idx=row * 2)
            source_list.append(cur_dev.s)
            gate_hm_tid = self.get_track_id(ridx_p, MOSWireType.G, 'sig', wire_idx=0, tile_idx=row)
            gate_list.append(self.connect_to_tracks(cur_dev.g, gate_hm_tid))
            drain_hm_tid = self.get_track_id(ridx_p, MOSWireType.DS, 'sup', wire_idx=0, tile_idx=row)
            out_list.append(self.connect_to_tracks(cur_dev.d, drain_hm_tid))
        self.set_mos_size()

        spread = seg // 8 if seg > 8 else 1
        lower_tidx = self.grid.coord_to_track(vm_layer, gate_list[0].lower, mode=RoundMode.NEAREST, even=True)
        upper_tidx = self.grid.coord_to_track(vm_layer, gate_list[0].upper, mode=RoundMode.NEAREST, even=True)
        vertical_ties = tr_manager.spread_wires(vm_layer, ['sig'] * spread,
                                                lower_tidx, upper_tidx, ('sig', 'sig'))
        vm_num = len(vertical_ties)
        vm_pitch = vertical_ties[1] - vertical_ties[0] if vm_num > 1 else 0
        vm_tid = TrackID(vm_layer, vertical_ties[0], width=tr_manager.get_width(vm_layer, 'sig'),
                         num=vm_num, pitch=vm_pitch)
        gate_vm = self.connect_to_tracks(gate_list, vm_tid)
        self.add_pin('G', gate_vm, connect=True)
        self.add_pin('VDD_OUT', out_list, connect=True)

        # Add VDD Rails
        self.connect_to_track_wires(source_list, vdd_list)
        self.add_pin('VDD', self.connect_wires(vdd_list), connect=True)

        self.sch_params = dict(
            w_p=wp if wp else self.get_tile_pinfo(dev_tiles[0]).get_row_place_info(ridx_p).row_info.width,
            lch=lch if lch else self.get_tile_pinfo(dev_tiles[0]).get_row_place_info(ridx_p).row_info.lch,
            intent=intent if intent else self.get_tile_pinfo(dev_tiles[0]).get_row_place_info(ridx_p).row_info.threshold,
            rows=rows,
            seg=seg,
        )


class PowerNMOS(MOSBase, LoggingBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        debug = params.get('debug', False)
        LoggingBase.__init__(self, "DCOMatrix",
                                "DCOMatrix.log",
                                log_level=LogLevel.INFO if not debug else LogLevel.DEBUG)
        MOSBase.__init__(self, temp_db, params, **kwargs)
        self.vss_track_list = []
        self.vdd_track_list = []
        self.offset_cols = 0
        self._n = "\n"

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__power_nmos

    @classmethod
    def get_params_info(cls) -> Mapping[str, str]:
        return dict(
            pinfo='The MOSBasePlaceInfo object.',
            rows='Number of rows.',
            seg='number of segments.',
            wn='nmos width.',
            lch='channel length.',
            intent='transistor threshold flavor.',
            ridx_n='nmos row index.',
            row_layout_info='Row layout information dictionary.',
            sig_locs='Signal track location dictionary.',
            show_pins='True to draw pin geometries.',
            per_finger_max_i='Maximum current per finger.',
            debug='true to print debug statements',
        )

    @classmethod
    def get_default_param_values(cls):
        # type: () -> Dict[str, Any]
        return dict(
            wn=None,
            lch=None,
            intent=None,
            ridx_n=0,
            row_layout_info=None,
            sig_locs=None,
            show_pins=True,
            per_finger_max_i=None,
            debug=False,
        )

    def draw_layout(self):
        rows: int = self.params['rows']
        seg: int = self.params['seg']
        ridx_n: int = self.params['ridx_n']
        sig_locs: Dict[str, Tuple[TrackType, TrackType]] = self.params['sig_locs']
        show_pins: bool = self.params['show_pins']
        pinfo_dict: Mapping[str, any] = dict(**self.params['pinfo'])

        wn: int = self.params['wn']
        lch: int = self.params['lch']
        intent: str = self.params['intent']

        # Adding tap rows consumes some rows, add them back
        total_rows_and_taps = rows + (rows // 2) + 1
        ptap_tiles = range(0, total_rows_and_taps, 3)   # skip tile 0 due to have correct patternwithout replicating taps
        dev_tiles = [tile for tile in range(1, total_rows_and_taps) if tile not in ptap_tiles]

        ptap_tile_dict = dict(name='ptap_tile')
        unit_tile_dict_no_flip = dict(name='unit_tile')
        unit_tile_dict_flip = dict(name='unit_tile', flip=True)

        unit_tile_idx_even = dev_tiles[1::2]
        unit_tile_idx_odd = dev_tiles[::2]

        tile_list = []
        for idx in range(total_rows_and_taps):
            if idx in unit_tile_idx_odd:
                tile_list.append(unit_tile_dict_no_flip)
            elif idx in unit_tile_idx_even:
                tile_list.append(unit_tile_dict_flip)
            else:
                tile_list.append(ptap_tile_dict)

        pinfo_dict['tiles'] = tile_list

        pinfo = MOSBasePlaceInfo.make_place_info(self.grid, pinfo_dict)
        self.draw_base(pinfo)
        self.log(f'Tiles: {self._n + self._n.join([f"{tile} {self.get_tile_pinfo(tile).name} {pinfo[0].get_tile_info(tile)[-1]}" for tile in range(total_rows_and_taps - 1, -1, -1)])}',
                 level=LogLevel.DEBUG)
        tr_manager = self.tr_manager

        hm_layer = self.conn_layer + 1
        vm_layer = hm_layer + 1

        device_list, vss_list, gate_list, drain_list, out_list = [], [], [], [], []
        for tile in ptap_tiles:
            self.log(f'Placing tap row on tile {tile}', level=LogLevel.DEBUG)
            ntap_port = self.add_substrate_contact(0, 0, tile_idx=tile, seg=seg)
            vss_tid = self.get_track_id(0, MOSWireType.DS, 'sup', wire_idx=0, tile_idx=tile)
            vss_list.append(self.connect_to_tracks(ntap_port, vss_tid))
        for row in dev_tiles:
            self.log(f'Adding PMOS on tile {row}', level=LogLevel.DEBUG)
            cur_dev = self.add_mos(ridx_n, 0, seg, tile_idx=row, g_on_s=True)
            device_list.append(cur_dev)
            drain_list.append(cur_dev.d)
            gate_hm_tid = self.get_track_id(ridx_n, MOSWireType.G, 'sig', wire_idx=0, tile_idx=row)
            gate_list.append(self.connect_to_tracks(cur_dev.g, gate_hm_tid))
            drain_hm_tid = self.get_track_id(ridx_n, MOSWireType.DS, 'sup', wire_idx=0, tile_idx=row)
            out_list.append(self.connect_to_tracks(cur_dev.s, drain_hm_tid))
        self.set_mos_size()

        spread = seg // 8 if seg > 8 else 1
        lower_tidx = self.grid.coord_to_track(vm_layer, gate_list[0].lower, mode=RoundMode.NEAREST)
        upper_tidx = self.grid.coord_to_track(vm_layer, gate_list[0].upper, mode=RoundMode.NEAREST)
        vertical_ties = tr_manager.spread_wires(vm_layer, ['sig'] * spread,
                                                lower_tidx, upper_tidx, ('sig', 'sig'))
        vm_num = len(vertical_ties)
        vm_pitch = vertical_ties[1] - vertical_ties[0] if vm_num > 1 else 0
        vm_tid = TrackID(vm_layer, vertical_ties[0], width=tr_manager.get_width(vm_layer, 'sig'),
                         num=vm_num, pitch=vm_pitch)
        gate_vm = self.connect_to_tracks(gate_list, vm_tid)
        self.add_pin('G', gate_vm, connect=True)
        self.add_pin('VDD_OUT', out_list, connect=True)

        # Add VDD Rails
        self.connect_to_track_wires(drain_list, vss_list)
        self.add_pin('VDD', self.connect_wires(vss_list), connect=True)

        self.sch_params = dict(
            w_n=wn if wn else self.get_tile_pinfo(dev_tiles[0]).get_row_place_info(ridx_n).row_info.width,
            lch=lch if lch else self.get_tile_pinfo(dev_tiles[0]).get_row_place_info(ridx_n).row_info.lch,
            intent=intent if intent else self.get_tile_pinfo(dev_tiles[0]).get_row_place_info(ridx_n).row_info.threshold,
            rows=rows,
            seg=seg,
        )
