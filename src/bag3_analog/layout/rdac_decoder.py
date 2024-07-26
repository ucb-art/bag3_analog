"""This module contains layout generator for the RDAC decoder"""

from typing import Mapping, Any, Optional, Type

from pybag.enum import PinMode

from bag.util.immutable import Param
from bag.design.module import Module
from bag.layout.template import TemplateDB
from bag.layout.enum import DrawTaps

from xbase.layout.mos.base import MOSBasePlaceInfo, MOSBase

from .rdac_decoder_row_col import RDACDecoderRow, RDACDecoderCol
from ..schematic.rdac_decoder import bag3_analog__rdac_decoder


class RDACDecoder(MOSBase):
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        MOSBase.__init__(self, temp_db, params, **kwargs)
        self._pg_coord0 = 0

    @property
    def pg_coord0(self) -> int:
        return self._pg_coord0

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__rdac_decoder

    @classmethod
    def get_params_info(cls) -> Mapping[str, str]:
        return dict(
            pinfo='The MOSBasePlaceInfo object.',
            seg_dict='Dictionary of segments of sub cell components',
            num_sel_col='Number of select inputs for column decoder',
            num_sel_row='Number of select inputs for row decoder',
            out_layer='Output layer ID',
        )

    @classmethod
    def get_default_param_values(cls) -> Mapping[str, Any]:
        return dict(out_layer=None)

    def draw_layout(self) -> None:
        pinfo = MOSBasePlaceInfo.make_place_info(self.grid, self.params['pinfo'])
        self.draw_base(pinfo)

        seg_dict: Mapping[str, Any] = self.params['seg_dict']
        num_sel_col: int = self.params['num_sel_col']
        num_sel_row: int = self.params['num_sel_row']
        out_layer: int = self.params['out_layer']
        num_sel = num_sel_row + num_sel_col
        num_in = 1 << num_sel
        num_rows = 1 << num_sel_row

        # make masters
        row_params = dict(pinfo=pinfo,
                          seg_dict=seg_dict,
                          num_sel=num_sel_row,
                          draw_taps=DrawTaps.LEFT,
                          out_layer=out_layer)
        row_master: RDACDecoderRow = self.new_template(RDACDecoderRow, params=row_params)
        row_ncols = row_master.num_cols

        col_params = dict(pinfo=pinfo,
                          seg_dict=seg_dict,
                          num_sel=num_sel_col,
                          num_rows=num_rows,
                          out_layer=out_layer)
        col_master: RDACDecoderCol = self.new_template(RDACDecoderCol, params=col_params)
        col_ncols = col_master.num_cols

        # --- Placement --- #
        row_pg = row_master.pg_tile0
        col_pg = col_master.pg_tile0
        self._pg_coord0 = pinfo.height * col_pg
        assert (row_pg & 1) == (col_pg & 1), 'Not supported yet. Row decoder layout floorplan ' \
                                             'requires minor modification'
        col_inst = self.add_tile(col_master, 0, 0)
        row_inst = self.add_tile(row_master, col_pg - row_pg, col_ncols + self.min_sep_col + row_ncols, flip_lr=True)

        self.set_mos_size()

        # --- Routing --- #
        # export inputs
        for idx in range(num_in):
            self.reexport(col_inst.get_port(f'in<{idx}>'))

        # export output
        self.reexport(row_inst.get_port('out'))

        # connect mid nodes
        for idx in range(num_rows):
            self.connect_wires([col_inst.get_pin(f'pout<{idx}>'), row_inst.get_pin(f'pin<{idx}>')])
            self.connect_wires([col_inst.get_pin(f'nout<{idx}>'), row_inst.get_pin(f'nin<{idx}>')])

        # select signals
        for idx in range(num_sel_col):
            self.reexport(col_inst.get_port(f'sel<{idx}>'))
        for idx in range(num_sel_row):
            _sel = self.extend_wires([row_inst.get_pin(f'sel<{idx}>')], lower=0)[0]
            self.add_pin(f'sel<{idx + num_sel_col}>', _sel, mode=PinMode.LOWER)

        # supplies
        hm_layer = self.conn_layer + 1
        vm_layer = hm_layer + 1
        xm_layer = vm_layer + 1
        ym_layer = xm_layer + 1
        xxm_layer = ym_layer + 1
        for sup in ('VDD', 'VSS'):
            self.connect_wires([col_inst.get_pin(sup, layer=hm_layer), row_inst.get_pin(sup, layer=hm_layer)], lower=0,
                               upper=self.bound_box.xh)
            self.connect_wires([col_inst.get_pin(sup, layer=xm_layer), row_inst.get_pin(sup, layer=xm_layer)], lower=0,
                               upper=self.bound_box.xh)
            sup_col = col_inst.get_pin(sup, layer=col_inst.master.place_info.arr_info.top_layer)
            sup_row = row_inst.get_pin(sup, layer=row_inst.master.place_info.arr_info.top_layer)
            sup_xxm = self.connect_wires([sup_col, sup_row], lower=min(0, sup_row.lower, sup_col.lower),
                                         upper=max(self.bound_box.xh, sup_row.upper, sup_col.upper))[0]
            self.add_pin(sup, sup_xxm)

        # set schematic parameters
        self.sch_params = dict(
            row_params=row_master.sch_params,
            col_params=col_master.sch_params,
        )
