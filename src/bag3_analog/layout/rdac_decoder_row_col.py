"""This module contains layout generators for the RDAC row and column decoders"""

from typing import Mapping, Any, Optional, Type, Union, Sequence

from pybag.enum import MinLenMode, RoundMode, PinMode

from bag.util.immutable import Param
from bag.design.module import Module
from bag.layout.template import TemplateDB
from bag.layout.routing.base import TrackID, WireArray
from bag.layout.enum import DrawTaps

from xbase.layout.enum import MOSWireType
from xbase.layout.mos.base import MOSBasePlaceInfo, MOSBase

from bag3_digital.layout.stdcells.gates import InvCore, PassGateCore
# from bag3_digital.layout.stdcells.and_complex import AndComplexRow, AndComplexCol
from bag3_digital.layout.stdcells.and_complex import AndComplexRow
from bag3_digital.layout.stdcells.and_complex import AndComplexColTall as AndComplexCol

from ..schematic.rdac_decoder_row_col import bag3_analog__rdac_decoder_row_col


class RDACDecoderRow(MOSBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        MOSBase.__init__(self, temp_db, params, **kwargs)
        self._pg_tile0 = 0

    @property
    def pg_tile0(self) -> int:
        # return the tile_idx of bottom-most passgate tile
        return self._pg_tile0

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__rdac_decoder_row_col

    @classmethod
    def get_params_info(cls) -> Mapping[str, str]:
        return dict(
            pinfo='The MOSBasePlaceInfo object.',
            seg_dict='Dictionary of segments of sub cell components',
            num_sel='Number of select inputs',
            draw_taps='"BOTH" or "LEFT" or "RIGHT" or "NONE"',
            out_layer='Output layer id',
        )

    @classmethod
    def get_default_param_values(cls) -> Mapping[str, Any]:
        return dict(draw_taps=DrawTaps.BOTH, out_layer=None)

    def draw_layout(self) -> None:
        pinfo = MOSBasePlaceInfo.make_place_info(self.grid, self.params['pinfo'])
        self.draw_base(pinfo)

        seg_dict: Mapping[str, Any] = self.params['seg_dict']
        num_sel: int = self.params['num_sel']
        out_layer: int = self.params['out_layer']
        num_in = 1 << num_sel
        draw_taps: Union[DrawTaps, str] = self.params['draw_taps']
        seg_tap = 4
        if isinstance(draw_taps, str):
            draw_taps = DrawTaps[draw_taps]

        # make masters
        pd0_tidx = self.get_track_index(1, MOSWireType.DS, 'sig', 0)
        pg_tidx = self.get_track_index(1, MOSWireType.G, 'sig', 0)
        nd1_tidx = self.get_track_index(0, MOSWireType.DS, 'sig', -1)
        inv_params_e = dict(pinfo=pinfo, seg=seg_dict['inv'], vertical_out=False)
        inv_params_o = dict(pinfo=pinfo, seg=seg_dict['inv'], vertical_out=False,
                            sig_locs={'pout': pd0_tidx, 'nout': nd1_tidx, 'nin': pg_tidx})
        inv_master_e = self.new_template(InvCore, params=inv_params_e)
        inv_master_o = self.new_template(InvCore, params=inv_params_o)
        inv_ncols = inv_master_e.num_cols

        pg_params = dict(pinfo=pinfo, seg=seg_dict['pg'], vertical_out=False)
        pg_master = self.new_template(PassGateCore, params=pg_params)
        pg_ncols = pg_master.num_cols

        and_params = dict(pinfo=pinfo, seg_dict=seg_dict['and'], num_in=num_sel)
        and_master: AndComplexRow = self.new_template(AndComplexRow, params=and_params)
        and_ncols = and_master.num_cols

        tap_ncols = self.get_tap_ncol(seg_tap)
        tot_ncols = max(and_ncols + self.min_sep_col + pg_ncols,
                        num_sel * inv_ncols + (num_sel - 1) * self.min_sep_col) + self.min_sep_col
        if draw_taps.has_left:
            tot_ncols += tap_ncols + self.sub_sep_col
            start_col = tap_ncols + self.sub_sep_col + self.min_sep_col // 2
        else:
            start_col = self.min_sep_col // 2
        if draw_taps.has_right:
            tot_ncols += tap_ncols + self.sub_sep_col

        hm_layer = self.conn_layer + 1
        vm_layer = hm_layer + 1
        xm_layer = vm_layer + 1
        ym_layer = xm_layer + 1

        assert pinfo.arr_info.top_layer >= vm_layer, f'Top layer must be at least up to layer {vm_layer}.'

        # --- Placement --- #
        vdd_hm_list, vss_hm_list = [], []

        # tile 1 and above: place left tap, and_complex, passgate, right tap
        self._pg_tile0 = 1
        w_sig_vm = self.tr_manager.get_width(vm_layer, 'sig')
        w_sig_xm = self.tr_manager.get_width(xm_layer, 'sig')
        w_sig_ym = self.tr_manager.get_width(ym_layer, 'sig')
        sel_vm_locs, selb_vm_locs = [], []
        sel_hm_list = [[] for _ in range(num_sel)]
        selb_hm_list = [[] for _ in range(num_sel)]
        pg_vm_locs, pg_ym_locs = [], []
        pg_out_vm_list, pg_out_ym_list = [], []
        and_in_list = and_master.nand_in_list
        for idx in range(num_in):
            vdd_tap_list, vss_tap_list = [], []
            tile_idx = idx + 1
            if draw_taps.has_left:
                self.add_tap(0, vdd_tap_list, vss_tap_list, tile_idx=tile_idx, seg=seg_tap)
            cur_col = start_col
            if draw_taps.has_right:
                self.add_tap(tot_ncols, vdd_tap_list, vss_tap_list, tile_idx=tile_idx, flip_lr=True, seg=seg_tap)

            _and = self.add_tile(and_master, tile_idx, cur_col)
            cur_col += and_ncols + self.min_sep_col
            _pg = self.add_tile(pg_master, tile_idx, cur_col)

            # supply
            vdd_hm_list.append(self.connect_wires([_and.get_pin('VDD'), _pg.get_pin('VDD')])[0])
            self.connect_to_track_wires(vdd_tap_list, vdd_hm_list[-1])
            vss_hm_list.append(self.connect_wires([_and.get_pin('VSS'), _pg.get_pin('VSS')])[0])
            self.connect_to_track_wires(vss_tap_list, vss_hm_list[-1])

            # pg enable
            self.connect_wires([_and.get_pin('out'), _pg.get_pin('en')])
            self.connect_wires([_and.get_pin('outb'), _pg.get_pin('enb')])

            # pg input and output
            pg_d = [_pg.get_pin('nd'), _pg.get_pin('pd')]
            if len(pg_vm_locs) == 0:
                _, pg_vm_locs = self.tr_manager.place_wires(vm_layer, ['sig', 'sig'],
                                                            center_coord=pg_d[0].bound_box.xm)
                _, pg_ym_locs = self.tr_manager.place_wires(ym_layer, ['sig', 'sig'],
                                                            center_coord=pg_d[0].bound_box.xm)
            _ym = (pg_d[0].bound_box.ym + pg_d[1].bound_box.ym) // 2
            _, pg_xm_locs = self.tr_manager.place_wires(xm_layer, ['sig', 'sig', 'sig'], center_coord=_ym)

            pg_s_vm = self.connect_to_tracks(_pg.get_pin('s'), TrackID(vm_layer, pg_vm_locs[0], w_sig_vm),
                                             min_len_mode=MinLenMode.MIDDLE)
            if pinfo.arr_info.top_layer >= ym_layer:
                pg_s_xm = self.connect_to_tracks(pg_s_vm, TrackID(xm_layer, pg_xm_locs[1], w_sig_xm),
                                                min_len_mode=MinLenMode.MIDDLE)
                pg_s_ym = self.connect_to_tracks(pg_s_xm, TrackID(ym_layer, pg_ym_locs[0], w_sig_ym),
                                                min_len_mode=MinLenMode.MIDDLE)

            self.connect_to_tracks(pg_d, TrackID(vm_layer, pg_vm_locs[-1], w_sig_vm))

            # passgate: s is output and d is input in the row decoder
            self.add_pin(f'nin<{idx}>', pg_d[0], label=f'in<{idx}>')
            self.add_pin(f'pin<{idx}>', pg_d[1], label=f'in<{idx}>')

            pg_out_vm_list.append(pg_s_vm)
            if pinfo.arr_info.top_layer >= ym_layer:
                pg_out_ym_list.append(pg_s_ym)

            # sel and selb
            if len(sel_vm_locs) == 0:
                for nand_idx, nand_in in enumerate(and_in_list):
                    _nand_out = _and.get_pin(f'nand_out{nand_idx}')
                    _, _vm_locs = self.tr_manager.place_wires(vm_layer, ['sig'] * (2 * nand_in + 1),
                                                              _nand_out.track_id.base_index, -1)
                    sel_vm_locs.extend(_vm_locs[0:-1:2])
                    selb_vm_locs.extend(_vm_locs[1:-1:2])
            bin_idx = f'{idx:0b}'.zfill(num_sel)
            for char_idx, bin_char in enumerate(bin_idx):
                sel_idx = num_sel - 1 - char_idx
                if bin_char == '1':
                    sel_hm_list[sel_idx].append(_and.get_pin(f'in<{sel_idx}>'))
                else:
                    selb_hm_list[sel_idx].append(_and.get_pin(f'in<{sel_idx}>'))
        self.set_mos_size(num_cols=tot_ncols, num_tiles=1 + num_in)

        # output
        out_vm = self.connect_wires(pg_out_vm_list)
        if out_layer is None or out_layer == ym_layer:
            out_ym = self.connect_wires(pg_out_ym_list, upper=self.bound_box.yh)[0]
            self.add_pin('out', out_ym, mode=PinMode.UPPER)
        else:
            out_vm = self.extend_wires(out_vm, upper=self.bound_box.yh)[0]
            self.add_pin('out', out_vm, mode=PinMode.UPPER)

        # tile 0: left tap, inverters, right tap
        vdd_tap_list, vss_tap_list = [], []
        vdd_hm_list0, vss_hm_list0 = [], []
        if draw_taps.has_left:
            self.add_tap(0, vdd_tap_list, vss_tap_list, tile_idx=0, seg=seg_tap)
        if draw_taps.has_right:
            self.add_tap(tot_ncols, vdd_tap_list, vss_tap_list, tile_idx=0, flip_lr=True, seg=seg_tap)

        cur_col = start_col
        for idx in range(num_sel):
            _master = inv_master_o if (idx & 1) else inv_master_e
            _inv = self.add_tile(_master, 0, cur_col)
            vdd_hm_list0.append(_inv.get_pin('VDD'))
            vss_hm_list0.append(_inv.get_pin('VSS'))

            sel_hm_list[idx].append(_inv.get_pin('nin'))
            sel_vm = self.connect_to_tracks(sel_hm_list[idx], TrackID(vm_layer, sel_vm_locs[idx], w_sig_vm),
                                            track_lower=0, track_upper=self.bound_box.yh)
            self.add_pin(f'sel<{idx}>', sel_vm, mode=PinMode.LOWER)
            selb_hm_list[idx].extend([_inv.get_pin('pout'), _inv.get_pin('nout')])
            self.connect_to_tracks(selb_hm_list[idx], TrackID(vm_layer, selb_vm_locs[idx], w_sig_vm),
                                   track_lower=0, track_upper=self.bound_box.yh)

            cur_col += inv_ncols + self.min_sep_col
        vss_hm_list.append(self.connect_wires(vss_hm_list0)[0])
        self.connect_to_track_wires(vss_tap_list, vss_hm_list[-1])
        vdd_hm_list.append(self.connect_wires(vdd_hm_list0)[0])
        self.connect_to_track_wires(vdd_tap_list, vdd_hm_list[-1])

        # --- Routing --- #
        # supply
        route_supplies(self, vdd_hm_list, vss_hm_list, self.bound_box.xh,
                       pinfo.arr_info.top_layer, draw_taps)

        self.sch_params = dict(
            inv_params=inv_master_e.sch_params,
            and_params=and_master.sch_params,
            pg_params=pg_master.sch_params,
            num_sel=num_sel,
            decoder_type='row',
        )


class RDACDecoderCol(MOSBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        MOSBase.__init__(self, temp_db, params, **kwargs)
        self._pg_tile0 = 0

    @property
    def pg_tile0(self) -> int:
        # return the tile_idx of bottom-most passgate tile
        return self._pg_tile0

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__rdac_decoder_row_col

    @classmethod
    def get_params_info(cls) -> Mapping[str, str]:
        return dict(
            pinfo='The MOSBasePlaceInfo object.',
            seg_dict='Dictionary of segments of sub cell components',
            num_sel='Number of select inputs',
            num_rows='Number of passgate rows',
        )

    def draw_layout(self) -> None:
        pinfo = MOSBasePlaceInfo.make_place_info(self.grid, self.params['pinfo'])
        self.draw_base(pinfo)

        seg_dict: Mapping[str, Any] = self.params['seg_dict']
        num_sel: int = self.params['num_sel']
        num_cols = 1 << num_sel
        num_rows: int = self.params['num_rows']
        seg_tap = 4

        # make masters
        pd0_tidx = self.get_track_index(1, MOSWireType.DS, 'sig', 0)
        pg_tidx = self.get_track_index(1, MOSWireType.G, 'sig', 0)
        nd1_tidx = self.get_track_index(0, MOSWireType.DS, 'sig', -1)
        inv_params_e = dict(pinfo=pinfo, seg=seg_dict['inv'], vertical_out=False)
        inv_params_o = dict(pinfo=pinfo, seg=seg_dict['inv'], vertical_out=False,
                            sig_locs={'pout': pd0_tidx, 'nout': nd1_tidx, 'nin': pg_tidx})
        inv_master_e = self.new_template(InvCore, params=inv_params_e)
        inv_master_o = self.new_template(InvCore, params=inv_params_o)
        inv_ncols = inv_master_e.num_cols

        pg_params = dict(pinfo=pinfo, seg=seg_dict['pg'], vertical_out=False)
        pg_master = self.new_template(PassGateCore, params=pg_params)
        pg_ncols = pg_master.num_cols

        and_params = dict(pinfo=pinfo, seg_dict=seg_dict['and'], num_in=num_sel)
        and_master: AndComplexCol = self.new_template(AndComplexCol, params=and_params)
        and_ncols = and_master.num_cols
        and_ntiles = and_master.num_tile_rows

        tot_ntiles = and_ntiles + num_rows
        self._pg_tile0 = and_ntiles

        tap_ncols = self.get_tap_ncol(seg_tap)

        hm_layer = self.conn_layer + 1
        vm_layer = hm_layer + 1
        xm_layer = vm_layer + 1

        # --- Placement --- #
        vdd_tap_list = [[] for _ in range(tot_ntiles)]
        vss_tap_list = [[] for _ in range(tot_ntiles)]
        vdd_hm_list = [[] for _ in range(tot_ntiles)]
        vss_hm_list = [[] for _ in range(tot_ntiles)]

        # left tap
        for tile_idx in range(tot_ntiles):
            self.add_tap(0, vdd_tap_list[tile_idx], vss_tap_list[tile_idx], tile_idx=tile_idx, seg=seg_tap)

        # column: and_col with passgates
        cur_col = tap_ncols + self.sub_sep_col + self.min_sep_col // 2
        sel_vm_list = [[] for _ in range(num_sel)]
        selb_vm_list = [[] for _ in range(num_sel)]
        pg_nd_list = [[] for _ in range(num_rows)]
        pg_pd_list = [[] for _ in range(num_rows)]

        for col_idx in range(num_cols):
            _and = self.add_tile(and_master, 0, cur_col)

            # and_complex supplies
            _and_vdd = _and.get_all_port_pins('VDD')
            _and_vss = _and.get_all_port_pins('VSS')
            for _tidx in range(and_ntiles):
                vdd_hm_list[_tidx].append(_and_vdd[_tidx])
                vss_hm_list[_tidx].append(_and_vss[_tidx])

            # sel and selb
            bin_idx = f'{col_idx:0b}'.zfill(num_sel)
            for char_idx, bin_char in enumerate(bin_idx):
                sel_idx = num_sel - 1 - char_idx
                if bin_char == '1':
                    sel_vm_list[sel_idx].append(_and.get_pin(f'in<{sel_idx}>'))
                else:
                    selb_vm_list[sel_idx].append(_and.get_pin(f'in<{sel_idx}>'))

            # and_complex outputs
            _en = _and.get_pin('out')
            _enb = _and.get_pin('outb')

            en_list, enb_list = [], []
            for row_idx in range(num_rows):
                _tidx = and_ntiles + row_idx
                _pg = self.add_tile(pg_master, _tidx, cur_col)

                # passgate supplies
                vdd_hm_list[_tidx].append(_pg.get_pin('VDD'))
                vss_hm_list[_tidx].append(_pg.get_pin('VSS'))

                # passgate outputs
                pg_nd_list[row_idx].append(_pg.get_pin('nd'))
                pg_pd_list[row_idx].append(_pg.get_pin('pd'))

                # passgate en and enb
                en_list.append(_pg.get_pin('en'))
                enb_list.append(_pg.get_pin('enb'))

                # passgate input
                ref_tidx = min(_en.track_id.base_index, _enb.track_id.base_index)
                _vm_tidx = self.tr_manager.get_next_track(vm_layer, ref_tidx, 'sig', 'sig', -1)
                _vm_tid = TrackID(vm_layer, _vm_tidx, _en.track_id.width)
                _in_vm = self.connect_to_tracks(_pg.get_pin('s'), _vm_tid, min_len_mode=MinLenMode.MIDDLE)
                self.add_pin(f'in<{row_idx * num_cols + col_idx}>', _in_vm)
            self.connect_to_track_wires(en_list, _en)
            self.connect_to_track_wires(enb_list, _enb)

            cur_col += max(and_ncols, pg_ncols) + self.min_sep_col

        # vm_locs for inverters
        and_in_list = and_master.nand_in_list
        vm_tidx0 = self.grid.coord_to_track(vm_layer, cur_col * self.sd_pitch, RoundMode.NEAREST)
        _, inv_vm_locs = self.tr_manager.place_wires(vm_layer, ['sig'] * (num_sel + 1), vm_tidx0)
        vm_col = self.grid.track_to_coord(vm_layer, inv_vm_locs[-1]) // self.sd_pitch

        # place inverters
        cur_col1 = cur_col
        w_sig_vm = self.tr_manager.get_width(vm_layer, 'sig')
        w_sig_xm = self.tr_manager.get_width(xm_layer, 'sig')
        sel_idx = 0
        inv_col = cur_col

        _selb_tidx = None
        _sel_tidx = None

        for tile_idx, and_in in enumerate(and_in_list):
            xm_locs = []
            _and_idx = tile_idx
            for _in_idx in range(and_in):
                tile_idx = sum(and_in_list[0:_and_idx + 1]) - _in_idx - 1
                _master = inv_master_o if (_in_idx & 1) else inv_master_e
                _inv = self.add_tile(_master, tile_idx, inv_col)

                # supplies
                vdd_hm_list[tile_idx].append(_inv.get_pin('VDD'))
                vss_hm_list[tile_idx].append(_inv.get_pin('VSS'))

                # get xm_layer wires
                if len(xm_locs) == 0:
                    for _tile_idx in range(num_sel):
                        vdd_tidx = self.get_track_index(-1, MOSWireType.DS, 'sup', 0, tile_idx=_tile_idx)
                        vss_tidx = self.get_track_index(0, MOSWireType.DS, 'sup', 0, tile_idx=_tile_idx)
                        vdd_ym = self.grid.track_to_coord(hm_layer, vdd_tidx)
                        vss_ym = self.grid.track_to_coord(hm_layer, vss_tidx)
                        tmp = self.tr_manager.place_wires(xm_layer, ['sig'] * 2, center_coord=(vss_ym + vdd_ym) // 2)
                        xm_locs.extend(tmp[1])

                _sel_idx = sel_idx + and_in - _in_idx - 1
                # output
                if not _selb_tidx:
                    _selb_tidx = self.grid.coord_to_track(vm_layer, _inv.bound_box.xl, RoundMode.LESS_EQ)
                _ref_tidx = _selb_tidx if not _sel_tidx else _sel_tidx
                _sel_tidx = self.tr_manager.get_next_track(vm_layer, _ref_tidx, 'sig', 'sig', 1)

                _selb = self.connect_to_tracks([_inv.get_pin('pout'), _inv.get_pin('nout')],
                                               TrackID(vm_layer, _selb_tidx, w_sig_vm))
                selb_vm_list[_sel_idx].append(_selb)
                self.connect_to_tracks(selb_vm_list[_sel_idx], TrackID(xm_layer, xm_locs[_sel_idx * 2], w_sig_xm))

                # input
                _sel = self.connect_to_tracks(_inv.get_pin('nin'),
                                              TrackID(vm_layer, _sel_tidx, w_sig_vm),
                                              track_lower=0)
                sel_vm_list[_sel_idx].append(_sel)
                self.connect_to_tracks(sel_vm_list[_sel_idx], TrackID(xm_layer, xm_locs[_sel_idx * 2 + 1], w_sig_xm))
                self.add_pin(f'sel<{_sel_idx}>', _sel, mode=PinMode.LOWER)

            cur_col1 = max(cur_col1, inv_col)
            sel_idx += and_in

        tot_ncols = max(cur_col1 - self.min_sep_col // 2, vm_col) + self.sub_sep_col + tap_ncols

        # right tap
        for tile_idx in range(tot_ntiles):
            self.add_tap(tot_ncols, vdd_tap_list[tile_idx], vss_tap_list[tile_idx], tile_idx=tile_idx, flip_lr=True,
                         seg=seg_tap)
        self.set_mos_size()

        # --- Routing --- #
        # passgate outputs
        for row_idx in range(num_rows):
            self.add_pin(f'nout<{row_idx}>', self.connect_wires(pg_nd_list[row_idx])[0], label=f'out<{row_idx}>',
                         connect=True, mode=PinMode.UPPER)
            self.add_pin(f'pout<{row_idx}>', self.connect_wires(pg_pd_list[row_idx])[0], label=f'out<{row_idx}>',
                         connect=True, mode=PinMode.UPPER)

        # supply
        vdd_hm, vss_hm = [], []
        for _tidx in range(tot_ntiles):
            vss_hm.append(self.connect_wires(vss_hm_list[_tidx])[0])
            self.connect_to_track_wires(vss_tap_list[_tidx], vss_hm[-1])
            vdd_hm.append(self.connect_wires(vdd_hm_list[_tidx])[0])
            self.connect_to_track_wires(vdd_tap_list[_tidx], vdd_hm[-1])
        route_supplies(self, vdd_hm, vss_hm, self.bound_box.xh, pinfo.arr_info.top_layer)

        self.sch_params = dict(
            inv_params=inv_master_e.sch_params,
            and_params=and_master.sch_params,
            pg_params=pg_master.sch_params,
            num_sel=num_sel,
            num_rows=num_rows,
            decoder_type='column',
        )


def route_supplies(cls: MOSBase, vdd_hm_list: Sequence[WireArray], vss_hm_list: Sequence[WireArray], xh: int, top_layer: int,
                   draw_taps: DrawTaps = DrawTaps.BOTH, ) -> None:
    vdd_hm = cls.connect_wires(vdd_hm_list, lower=0, upper=xh)[0]
    vss_hm = cls.connect_wires(vss_hm_list, lower=0, upper=xh)[0]
    vdd_pin_list = [vdd_hm]
    vss_pin_list = [vss_hm]

    hm_layer = cls.conn_layer + 1
    vm_layer = hm_layer + 1
    xm_layer = vm_layer + 1
    ym_layer = xm_layer + 1
    xxm_layer = ym_layer + 1

    x_layers = range(xm_layer, top_layer + 1, 2)

    for _hm_layer in x_layers:
        _vm_layer = _hm_layer - 1
        vss_vm_list, vdd_vm_list = [], []
        if draw_taps.has_left:
            vss_vm_list.append(cls.grid.coord_to_track(_vm_layer, vss_hm.lower, RoundMode.GREATER_EQ))
            vdd_vm_list.append(cls.tr_manager.get_next_track(_vm_layer, vss_vm_list[-1], 'sup', 'sup', up=1))
        if draw_taps.has_right:
            vss_vm_list.append(cls.grid.coord_to_track(_vm_layer, vss_hm.upper, RoundMode.LESS_EQ))
            vdd_vm_list.append(cls.tr_manager.get_next_track(_vm_layer, vss_vm_list[-1], 'sup', 'sup', up=-1))
        w_sup_vm = cls.tr_manager.get_width(_vm_layer, 'sup')
        vdd_vm = cls.connect_to_tracks(vdd_hm, TrackID(_vm_layer, vdd_vm_list[0], w_sup_vm, len(vdd_vm_list),
                                                       vdd_vm_list[-1] - vdd_vm_list[0]))
        vss_vm = cls.connect_to_tracks(vss_hm, TrackID(_vm_layer, vss_vm_list[0], w_sup_vm, len(vss_vm_list),
                                                       vss_vm_list[-1] - vss_vm_list[0]))

        vdd_hm_l = cls.grid.coord_to_track(_hm_layer, vdd_hm[0].bound_box.ym, RoundMode.NEAREST)
        vdd_hm_l1 = cls.grid.coord_to_track(_hm_layer, vdd_hm[1].bound_box.ym, RoundMode.NEAREST)
        w_sup_hm = cls.tr_manager.get_width(_hm_layer, 'sup')
        vdd_hm = cls.connect_to_tracks(vdd_vm, TrackID(_hm_layer, vdd_hm_l, w_sup_hm, vdd_hm.track_id.num,
                                                       vdd_hm_l1 - vdd_hm_l), track_lower=0, track_upper=xh)
        vdd_pin_list.append(vdd_hm)
        vss_hm_l = cls.grid.coord_to_track(_hm_layer, vss_hm[0].bound_box.ym, RoundMode.NEAREST)
        vss_hm_l1 = cls.grid.coord_to_track(_hm_layer, vss_hm[1].bound_box.ym, RoundMode.NEAREST)
        vss_hm = cls.connect_to_tracks(vss_vm, TrackID(_hm_layer, vss_hm_l, w_sup_hm, vss_hm.track_id.num,
                                                       vss_hm_l1 - vss_hm_l), track_lower=0, track_upper=xh)
        vss_pin_list.append(vss_hm)
    cls.add_pin('VDD', vdd_pin_list)
    cls.add_pin('VSS', vss_pin_list)
