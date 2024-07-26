# SPDX-License-Identifier: BSD-3-Clause AND Apache-2.0
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

from typing import Any, Dict, List, Optional, Type, cast, Iterable, Union, Tuple

from pybag.enum import RoundMode, Direction
from pybag.core import BBox, BBoxArray

from bag.util.immutable import Param
from bag.design.module import Module
from bag.layout.routing.base import TrackID, WireArray
from bag.layout.template import TemplateDB

from xbase.layout.res.base import ResBasePlaceInfo, ResArrayBase

from bag3_analog.layout.util import translate_layers

from ...schematic.res_ladder import bag3_analog__res_ladder


class ResLadder(ResArrayBase):
    """An array of resistors to be used as a resistor ladder, e.g. for RDAC.
    Resistors are stringed together in a Z-pattern, starting from the top left.

    Assumption
    - Top layer is an even layer
    - Resistors are sized tall enough to fit enough top layer wires

    """
    def __init__(self, temp_db: TemplateDB, params: Param, **kwargs: Any) -> None:
        ResArrayBase.__init__(self, temp_db, params, **kwargs)
        self._sup_name = ''
        self._core_coord0 = 0

    @property
    def core_coord0(self) -> int:
        return self._core_coord0

    @classmethod
    def get_schematic_class(cls) -> Optional[Type[Module]]:
        return bag3_analog__res_ladder

    @classmethod
    def get_params_info(cls) -> Dict[str, str]:
        return dict(
            pinfo='The ResBasePlaceInfo object.',
            nx_dum='Number of dummies on each side, X direction',
            ny_dum='Number of dummies on each side, Y direction',
            top_vdd='True to make the top connection VDD',
            bot_vss='True to make the bottom connection VSS',
            mres_l='Length of vm_layer metal resistors between bottom and out<0>',
        )

    @classmethod
    def get_default_param_values(cls) -> Dict[str, Any]:
        return dict(nx_dum=0, ny_dum=0, top_vdd=True, bot_vss=True, mres_l=100)

    def draw_layout(self) -> None:
        """General strategy to achieve good wire matching:
        1) Draw the metal setup for one unit cell
        2) Replicate / translate that unit metal setup to all units
        3) Connect the ladder array
        4) Connect the dummies to supply bars
        5) Connect substrate connections and complete connections up to vm_layer
        6) Draw xm_layer ladder tap and supply connections
        """
        pinfo = cast(ResBasePlaceInfo, ResBasePlaceInfo.make_place_info(self.grid, self.params['pinfo']))
        self.draw_base(pinfo)
        # Well tap connection
        self._sup_name = 'VDD' if \
            cast(ResBasePlaceInfo, self.place_info).res_config['sub_type_default'] == 'ntap' else 'VSS'

        assert pinfo.top_layer >= pinfo.conn_layer + 3

        unit_metal_dict = self._draw_unit_metal()
        full_metal_dict = self._array_metal_and_connect(unit_metal_dict)
        self._connect_ladder(full_metal_dict)
        self._connect_dummies(full_metal_dict)
        self._connect_supplies_and_substrate(full_metal_dict)
        mres_info = self._connect_top(full_metal_dict)

        ny_dum: int = self.params['ny_dum']
        self._core_coord0 = pinfo.height * ny_dum

        self.sch_params = dict(
            w=pinfo.w_res,
            l=pinfo.l_res,
            res_type=pinfo.res_type,
            nx=pinfo.nx,
            ny=pinfo.ny,
            nx_dum=self.params['nx_dum'],
            ny_dum=ny_dum,
            top_vdd=self.params['top_vdd'],
            bot_vss=self.params['bot_vss'],
            sup_name=self._sup_name,
            mres_info=mres_info,
        )

    def _draw_unit_metal(self) -> Dict[int, List[Union[WireArray, List[WireArray]]]]:
        """Draws metal wires over a unit cell. Returns all the metal wire arrays"""
        tr_manager = self.tr_manager
        conn_layer = self.place_info.conn_layer
        hm_layer = conn_layer + 1
        vm_layer = hm_layer + 1
        w_sig_hm = tr_manager.get_width(hm_layer, 'sig')
        w_sig_vm = tr_manager.get_width(vm_layer, 'sig')

        # Draw unit cell conn_layer wires
        # conn layer: Require tracks for 1 sup, 3 sig on top and bottom, with spacing for 1 sig in between
        bot_lower = self.grid.coord_to_track(hm_layer, 0)
        bot_pport = cast(BBox, self.get_device_port(0, 0, 'MINUS'))
        bot_upper = self.grid.coord_to_track(hm_layer, bot_pport.ym, RoundMode.LESS_EQ)
        avail_upper = tr_manager.get_next_track(hm_layer, bot_lower, 'sup', 'sig', 3)
        bot_upper = max(bot_upper, avail_upper)
        bot_locs = tr_manager.spread_wires(hm_layer, ['sup', 'sig', 'sig', 'sig'],
                                           bot_lower, bot_upper, sp_type=('sup', 'sig'), alignment=1)

        top_upper = self.grid.coord_to_track(hm_layer, self.place_info.height)
        top_pport = cast(BBox, self.get_device_port(0, 0, 'PLUS'))
        top_lower = self.grid.coord_to_track(hm_layer, top_pport.ym, RoundMode.GREATER_EQ)
        avail_lower = tr_manager.get_next_track(hm_layer, top_upper, 'sup', 'sig', -3)
        top_lower = min(top_lower, avail_lower)
        top_locs = tr_manager.spread_wires(hm_layer, ['sig', 'sig', 'sig', 'sup'],
                                           top_lower, top_upper, sp_type=('sup', 'sig'), alignment=-1)

        # there should be at least one track separation between bot_upper and top_lower for vm_layer line end spacing
        avail_idx = tr_manager.get_next_track(hm_layer, bot_upper, 'sig', 'sig', 2)
        if top_lower < avail_idx:
            raise ValueError(f'Not possible to fit necessary routing tracks on hm_layer={hm_layer}. '
                             f'Increase unit cell length')
        hm_locs = bot_locs + top_locs

        lower = self.grid.coord_to_track(vm_layer, 0)
        upper = self.grid.coord_to_track(vm_layer, self.place_info.width)
        try:
            vm_locs = tr_manager.spread_wires(vm_layer, ['sup', 'sig', 'sig', 'sig', 'sup'],
                                              lower, upper, sp_type=('sup', 'sig'), alignment=0)
        except ValueError:
            raise ValueError(f'Not possible to fit necessary routing tracks on vm_layer={vm_layer}. '
                             f'Increase unit cell width')

        # Determine x-dimensions for hm_layer
        ext_x, ext_y = self.grid.get_via_extensions(Direction.LOWER, hm_layer, w_sig_hm, w_sig_vm)
        vm_w = self.grid.get_wire_total_width(vm_layer, w_sig_vm)
        vm_w2 = vm_w // 2
        ext_x += vm_w2
        hm_w = self.grid.get_wire_total_width(hm_layer, w_sig_hm)
        ext_y += hm_w // 2

        hm_dims = [
            (0, self.place_info.width),
            [(self.grid.track_to_coord(vm_layer, vm_locs[3]) - ext_x - self.place_info.width,
             self.grid.track_to_coord(vm_layer, vm_locs[1]) + ext_x),
             (self.grid.track_to_coord(vm_layer, vm_locs[3]) - ext_x,
              self.grid.track_to_coord(vm_layer, vm_locs[1]) + ext_x + self.place_info.width)],
            (self.grid.track_to_coord(vm_layer, vm_locs[1]) - ext_x,
             self.grid.track_to_coord(vm_layer, vm_locs[3]) + ext_x),
            (self.grid.track_to_coord(vm_layer, vm_locs[1]) - ext_x,
             self.grid.track_to_coord(vm_layer, vm_locs[3]) + ext_x),
            (self.grid.track_to_coord(vm_layer, vm_locs[1]) - ext_x,
             self.grid.track_to_coord(vm_layer, vm_locs[3]) + ext_x),
            (self.grid.track_to_coord(vm_layer, vm_locs[1]) - ext_x,
             self.grid.track_to_coord(vm_layer, vm_locs[3]) + ext_x),
            [(self.grid.track_to_coord(vm_layer, vm_locs[3]) - ext_x - self.place_info.width,
              self.grid.track_to_coord(vm_layer, vm_locs[1]) + ext_x),
             (self.grid.track_to_coord(vm_layer, vm_locs[3]) - ext_x,
              self.grid.track_to_coord(vm_layer, vm_locs[1]) + ext_x + self.place_info.width)],
            (0, self.place_info.width),
        ]

        vm_dims = [
            (0, self.place_info.height),
            (self.grid.track_to_coord(hm_layer, hm_locs[1]) - ext_y,
             self.grid.track_to_coord(hm_layer, hm_locs[-2]) + ext_y),
            [(self.grid.track_to_coord(hm_layer, hm_locs[-4]) - ext_y - self.place_info.height,
             self.grid.track_to_coord(hm_layer, hm_locs[3]) + ext_y),
             (self.grid.track_to_coord(hm_layer, hm_locs[-4]) - ext_y,
             self.grid.track_to_coord(hm_layer, hm_locs[3]) + ext_y + self.place_info.height)],
            (self.grid.track_to_coord(hm_layer, hm_locs[1]) - ext_y,
             self.grid.track_to_coord(hm_layer, hm_locs[-2]) + ext_y),
            (0, self.place_info.height),
        ]

        # Draw wires
        metal_dict = {}
        for layer, info in [(hm_layer, zip(hm_locs, hm_dims)), (vm_layer, zip(vm_locs, vm_dims))]:
            layer_metal = []
            lay_w = w_sig_vm if layer == vm_layer else w_sig_hm
            for loc, dims in info:
                if isinstance(dims[0], Iterable):
                    _ans = []
                    for _dim in dims:
                        _ans.append(self.add_wires(layer, loc, _dim[0], _dim[1], width=lay_w))
                else:
                    _ans = self.add_wires(layer, loc, dims[0], dims[1], width=lay_w)
                layer_metal.append(_ans)
            metal_dict[layer] = layer_metal

        return metal_dict

    def _array_metal_and_connect(self, unit_metal_dict: Dict[int, List[Union[WireArray, List[WireArray]]]]
                                 ) -> Dict[Tuple[int, int], Dict[int, List[Union[WireArray, List[WireArray]]]]]:
        """Takes the unit metal dictionary and arrays it over the whole array. Also connects
        to the PLUS and MINUS terminals. Returns a dictionary mapping (xidx, yidx) to unit
        metal dictionaries for each unit cell. Actual connecting up of these wires happens
        in separate functions."""

        nx = self.place_info.nx
        ny = self.place_info.ny

        tr_manager = self.tr_manager
        conn_layer = self.place_info.conn_layer
        hm_layer = conn_layer + 1
        vm_layer = hm_layer + 1
        w_sig_hm = tr_manager.get_width(hm_layer, 'sig')
        w_sig_vm = tr_manager.get_width(vm_layer, 'sig')

        prim_lay_purp = self.tech_cls.tech_info.get_lay_purp_list(conn_layer)[0]

        full_metal_dict = {}
        for yidx in range(ny):
            for xidx in range(nx):
                idx = (xidx, yidx)
                xform = self._get_transform(xidx, yidx)

                # Array wire arrays
                _unit_info = {}
                for layer, ref_met_list in unit_metal_dict.items():
                    lay_w = w_sig_vm if layer == vm_layer else w_sig_hm
                    layer_metals = []
                    for ref_met in ref_met_list:
                        if isinstance(ref_met, Iterable):
                            met = []
                            for _elem in ref_met:
                                _met = _elem.get_transform(xform)
                                self.add_wires(_met.layer_id, _met.track_id.base_index,
                                               _met.lower, _met.upper, width=lay_w)
                                met.append(_met)
                        else:
                            met = ref_met.get_transform(xform)
                            self.add_wires(met.layer_id, met.track_id.base_index,
                                           met.lower, met.upper, width=lay_w)
                        layer_metals.append(met)
                    _unit_info[layer] = layer_metals
                full_metal_dict[idx] = _unit_info

                # Connect resistors plus and minus
                pin_l_bbox = self.get_device_port(xidx, yidx, 'PLUS' if yidx % 2 else 'MINUS')
                self.connect_bbox_to_track_wires(Direction.LOWER, prim_lay_purp, pin_l_bbox,
                                                 _unit_info[hm_layer][3])
                pin_h_bbox = self.get_device_port(xidx, yidx, 'MINUS' if yidx % 2 else 'PLUS')
                self.connect_bbox_to_track_wires(Direction.LOWER, prim_lay_purp, pin_h_bbox,
                                                 _unit_info[hm_layer][-4])

        return full_metal_dict

    def _connect_ladder(self,
                        full_metal_dict: Dict[Tuple[int, int], Dict[int, List[Union[WireArray, List[WireArray]]]]]):
        """Connects up the internal ladder"""

        nx = self.place_info.nx
        ny = self.place_info.ny
        nx_dum = self.params['nx_dum']
        ny_dum = self.params['ny_dum']

        #TODO: Add support for clean no-dummy generation. For now these assertions
        #      are here to ensure clean ResLadder generation

        assert(nx_dum > 0 and ny_dum > 0, "ResLadder generation without dummies is not currently supported.")

        nx_core = nx - 2 * nx_dum
        ny_core = ny - 2 * ny_dum

        conn_layer = self.place_info.conn_layer
        hm_layer = conn_layer + 1
        vm_layer = hm_layer + 1

        # TODO: simplify the logic here
        # Connect from bottom up
        for yidx in range(ny_core):
            for xidx in range(nx_core):
                unit_dict = full_metal_dict[(nx_dum + xidx, ny_dum + yidx)]
                # Avoid using connect warrs. We want to match the wires
                if xidx == 0:
                    self.draw_vias_on_intersections(
                        unit_dict[hm_layer][-4 if yidx % 2 else 3],
                        unit_dict[vm_layer][2])
                    self.draw_vias_on_intersections(
                        [unit_dict[hm_layer][3 if yidx % 2 else -4],
                         unit_dict[hm_layer][1 if yidx % 2 else -2][-1]],
                        unit_dict[vm_layer][3])
                elif xidx == nx_core - 1:
                    self.draw_vias_on_intersections(
                        unit_dict[hm_layer][3 if yidx % 2 else -4],
                        unit_dict[vm_layer][2])
                    self.draw_vias_on_intersections(
                        unit_dict[hm_layer][-4 if yidx % 2 else 3],
                        unit_dict[vm_layer][1])
                    self.draw_vias_on_intersections(
                        unit_dict[hm_layer][1 if (yidx % 2) ^ (nx_core % 2) else -2],
                        unit_dict[vm_layer][1])
                else:
                    if xidx % 2 == 1:
                        self.draw_vias_on_intersections(
                            [unit_dict[hm_layer][3 if yidx % 2 else -4],
                             unit_dict[hm_layer][1 if yidx % 2 else -2][0]],
                            unit_dict[vm_layer][1])
                        self.draw_vias_on_intersections(
                            [unit_dict[hm_layer][-4 if yidx % 2 else 3],
                             unit_dict[hm_layer][-2 if yidx % 2 else 1][-1]],
                            unit_dict[vm_layer][-2])
                    else:
                        self.draw_vias_on_intersections(
                            [unit_dict[hm_layer][3 if yidx % 2 else -4],
                             unit_dict[hm_layer][1 if yidx % 2 else -2][-1]],
                            unit_dict[vm_layer][-2])
                        self.draw_vias_on_intersections(
                            [unit_dict[hm_layer][-4 if yidx % 2 else 3],
                             unit_dict[hm_layer][-2 if yidx % 2 else 1][0]],
                            unit_dict[vm_layer][1])

    def _connect_dummies(self,
                         full_metal_dict: Dict[Tuple[int, int], Dict[int, List[Union[WireArray, List[WireArray]]]]]):
        """Connects up PLUS and MINUS pins of the dummies"""

        nx = self.place_info.nx
        ny = self.place_info.ny
        nx_dum = self.params['nx_dum']
        ny_dum = self.params['ny_dum']

        ny_core = ny - 2 * ny_dum

        conn_layer = self.place_info.conn_layer
        hm_layer = conn_layer + 1
        vm_layer = hm_layer + 1

        # Connect from bottom up
        for yidx in range(ny):
            for xidx in range(nx):
                if nx_dum <= xidx <= nx - nx_dum - 1 and ny_dum <= yidx <= ny - ny_dum - 1:
                    continue
                unit_dict = full_metal_dict[(xidx, yidx)]
                # Skip the top and bottoms
                if not (xidx == nx_dum and yidx == ny_dum - 1):
                    self.draw_vias_on_intersections(
                        [unit_dict[hm_layer][-1], unit_dict[hm_layer][-4]], unit_dict[vm_layer][2])
                if not (yidx == ny - ny_dum and xidx == (nx - nx_dum - 1 if ny_core % 2 else nx_dum)):
                    self.draw_vias_on_intersections(
                        [unit_dict[hm_layer][0], unit_dict[hm_layer][3]], unit_dict[vm_layer][2])
                self.draw_vias_on_intersections(
                    [unit_dict[hm_layer][3], unit_dict[hm_layer][-4]],
                    [unit_dict[vm_layer][1], unit_dict[vm_layer][-2]])

    def _connect_supplies_and_substrate(
            self, full_metal_dict: Dict[Tuple[int, int], Dict[int, List[Union[WireArray, List[WireArray]]]]]):
        """Draw substrate connections and supply wires"""
        nx = self.place_info.nx
        ny = self.place_info.ny

        tr_manager = self.tr_manager
        conn_layer = self.place_info.conn_layer
        hm_layer = conn_layer + 1
        vm_layer = hm_layer + 1
        xm_layer = vm_layer + 1
        w_sup_xm = tr_manager.get_width(xm_layer, 'sup')
        prim_lp = self.tech_cls.tech_info.get_lay_purp_list(conn_layer)[0]

        # If we have bulk, connect bulk
        # Assume that the bulk port is on conn_layer and can be simply connected
        # to the conn_layer supply lines.
        if self.has_substrate_port:
            for yidx in range(ny):
                for xidx in range(nx):
                    hm_warr_list = full_metal_dict[(xidx, yidx)][hm_layer]
                    bulk_bbox = self.get_device_port(xidx, yidx, 'BULK')
                    if isinstance(bulk_bbox, BBoxArray) and bulk_bbox.ny > 1:
                        bulk_bbox0 = bulk_bbox.get_bbox(0)
                        bulk_bbox1 = bulk_bbox.get_bbox(bulk_bbox.ny - 1)
                        if yidx & 1:
                            # Unit cell is placed in MX orientation in odd rows,
                            # so top & bottom bulk connections are flipped
                            bulk_bbox0, bulk_bbox1 = bulk_bbox1, bulk_bbox0
                    else:
                        bulk_bbox0 = bulk_bbox1 = bulk_bbox
                    self.connect_bbox_to_track_wires(Direction.LOWER, prim_lp, bulk_bbox0, hm_warr_list[0])
                    self.connect_bbox_to_track_wires(Direction.LOWER, prim_lp, bulk_bbox1, hm_warr_list[-1])

        # Connect hm_layer supplies to vm_layer supplies
        for yidx in range(ny):
            for xidx in range(nx):
                unit_dict = full_metal_dict[(xidx, yidx)]
                self.connect_to_track_wires(
                    [unit_dict[hm_layer][0], unit_dict[hm_layer][-1]],
                    [unit_dict[vm_layer][0], unit_dict[vm_layer][-1]],
                )

        # Connect supplies up to xm_layer
        xm_list = []
        for yidx, wire_idx in [(0, 0), (ny - 1, -1)]:
            hm_tidx = full_metal_dict[(0, yidx)][hm_layer][wire_idx].track_id.base_index
            xm_tidx = translate_layers(self.grid, hm_layer, hm_tidx, xm_layer)
            vm_list = []
            for xidx in range(nx):
                vm_list.append(full_metal_dict[(xidx, yidx)][vm_layer][0])
                vm_list.append(full_metal_dict[(xidx, yidx)][vm_layer][-1])
            xm_list.append(self.connect_to_tracks(vm_list, TrackID(xm_layer, xm_tidx, w_sup_xm)))

        # Add pin
        sup_warr = self.connect_wires(xm_list)
        self.add_pin(self._sup_name, sup_warr)

    def _connect_top(
            self, full_metal_dict: Dict[Tuple[int, int], Dict[int, List[Union[WireArray, List[WireArray]]]]]
            ) -> Tuple[int, int, int]:
        """Draw ladder taps connections. Resistors the width, length, layer of the metal resistor"""
        nx = self.place_info.nx
        ny = self.place_info.ny
        nx_dum = self.params['nx_dum']
        ny_dum = self.params['ny_dum']

        nx_core = nx - 2 * nx_dum
        ny_core = ny - 2 * ny_dum

        tr_manager = self.tr_manager
        conn_layer = self.place_info.conn_layer
        hm_layer = conn_layer + 1
        vm_layer = hm_layer + 1
        xm_layer = vm_layer + 1
        w_sup_xm = tr_manager.get_width(xm_layer, 'sup')
        w_sig_xm = tr_manager.get_width(xm_layer, 'sig')

        # Extra tap connections to be consistent
        for yidx in range(ny_core):
            xidx = nx_core - 1 if yidx % 2 else 0
            unit_info = full_metal_dict[(xidx + nx_dum, yidx + ny_dum)]
            self.draw_vias_on_intersections(
                unit_info[hm_layer][3], unit_info[vm_layer][-2 if yidx % 2 else 1])

        # Draw tap wires
        unit_height = self.place_info.height
        xm_warr_list = []
        for yidx in range(ny_core):
            yc = unit_height // 2 + (yidx + ny_dum) * unit_height
            xm_tidx_list = tr_manager.place_wires(xm_layer, ['sig'] * nx_core, center_coord=yc)[1]
            for xidx, xm_tidx in enumerate(xm_tidx_list):
                xloc = nx - (xidx + nx_dum) - 1 if yidx % 2 else xidx + nx_dum
                unit_info = full_metal_dict[(xloc, + yidx + ny_dum)]
                vm = unit_info[vm_layer][-2 if yidx % 2 else 1]
                xm_warr_list.append(
                    self.connect_to_tracks(vm, TrackID(xm_layer, xm_tidx, w_sig_xm)))

        # Stretch tap wires left and right
        lower = min([xm.lower for xm in xm_warr_list])
        upper = max([xm.upper for xm in xm_warr_list])
        xm_warr_list = self.extend_wires(xm_warr_list, lower=lower, upper=upper)

        # Add pins names
        for xidx, xm_warr in enumerate(xm_warr_list):
            hide = xidx == 0 and not self.grid.tech_info.has_res_metal()  # Can't isolate bottom and idx0
            self.add_pin(f'out<{xidx}>', xm_warr, hide=hide)

        # Draw top and bottom
        bot_unit_info = full_metal_dict[(nx_dum, ny_dum)]
        bot_tidx = translate_layers(self.grid, hm_layer,
                                    bot_unit_info[hm_layer][0].track_id.base_index, xm_layer)
        avail_bot_tidx = tr_manager.get_next_track(xm_layer, xm_warr_list[0].track_id.base_index, 'sig', 'sup', -1)
        bot_tidx = min(bot_tidx, avail_bot_tidx)
        bot_warr = self.connect_to_tracks(
            bot_unit_info[vm_layer][2][0], TrackID(xm_layer, bot_tidx, w_sup_xm), track_lower=lower, track_upper=upper)
        self.add_pin('VSS' if self.params['bot_vss'] else 'bottom', bot_warr)

        top_unit_info = full_metal_dict[(nx - nx_dum - 1 if ny_core % 2 else nx_dum, ny - ny_dum - 1)]
        top_tidx = translate_layers(self.grid, hm_layer,
                                    top_unit_info[hm_layer][-1].track_id.base_index, xm_layer)
        avail_top_tidx = tr_manager.get_next_track(xm_layer, xm_warr_list[-1].track_id.base_index, 'sig', 'sup', 1)
        top_tidx = max(top_tidx, avail_top_tidx)
        top_warr = self.connect_to_tracks(
            top_unit_info[vm_layer][2][-1], TrackID(xm_layer, top_tidx, w_sup_xm), track_lower=lower, track_upper=upper)
        self.add_pin('VDD' if self.params['top_vdd'] else 'top', top_warr)

        # Add metal resistor between bottom and out<0>
        mres_l = self.params['mres_l']
        w_sig_hm = tr_manager.get_width(hm_layer, 'sig')
        hm_w = self.grid.get_wire_total_width(hm_layer, w_sig_hm)
        w_sig_vm = tr_manager.get_width(vm_layer, 'sig')
        vm_w = self.grid.get_wire_total_width(vm_layer, w_sig_vm)
        ext_x, ext_y = self.grid.get_via_extensions(Direction.LOWER, hm_layer, w_sig_hm, w_sig_vm)
        ref_info = full_metal_dict[(nx_dum, ny_dum)]
        xl = self.grid.track_to_coord(
            vm_layer, ref_info[vm_layer][2][0].track_id.base_index) - vm_w // 2
        xh = xl + vm_w
        yl = ref_info[vm_layer][2][0].bound_box.ym + hm_w // 2 + ext_y
        yh = yl + mres_l
        if self.has_res_metal():
            self.add_res_metal(vm_layer, BBox(xl, yl, xh, yh))

        # Add extra conn if appropriate
        if self.params['top_vdd'] and self._sup_name == 'VDD':
            self.draw_vias_on_intersections(top_unit_info[hm_layer][-1], top_unit_info[vm_layer][2][1])
        if self.params['bot_vss'] and self._sup_name == 'VSS':
            self.draw_vias_on_intersections(bot_unit_info[hm_layer][0], bot_unit_info[vm_layer][2][0])

        return vm_w, mres_l, vm_layer
