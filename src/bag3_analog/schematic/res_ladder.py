# SPDX-License-Identifier: Apache-2.0
# Copyright 2020 Blue Cheetah Analog Design Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# -*- coding: utf-8 -*-

from typing import Dict, Any, Tuple

import pkg_resources
from pathlib import Path

from bag.design.module import Module
from bag.design.database import ModuleDB
from bag.util.immutable import Param


# noinspection PyPep8Naming
class bag3_analog__res_ladder(Module):
    """Module for library bag3_analog cell res_ladder.

    Fill in high level description here.
    """

    yaml_file = pkg_resources.resource_filename(__name__,
                                                str(Path('netlist_info',
                                                         'res_ladder.yaml')))

    def __init__(self, database: ModuleDB, params: Param, **kwargs: Any) -> None:
        Module.__init__(self, self.yaml_file, database, params, **kwargs)
        self.has_idx0 = False  # True if idx 0 is there. Requires metal resistors to isolate idx0 from bottom
        self.top_vdd = False  # Set in design. Used in RDAC level
        self.bot_vss = False

    @classmethod
    def get_params_info(cls) -> Dict[str, str]:
        """Returns a dictionary from parameter names to descriptions.

        Returns
        -------
        param_info : Optional[Dict[str, str]]
            dictionary from parameter names to descriptions.
        """
        return dict(
            w="Resistor width",
            l="Resistor length",
            res_type="Resistor flavor",
            nx="Number of units in the X direction",
            ny="Number of units in the Y direction",
            nx_dum="Number of dummies on each side, X direction",
            ny_dum="Number of dummies on each side, Y direction",
            top_vdd='True to make the top connection VDD',
            bot_vss='True to make the bottom connection VSS',
            sup_name="Supply name to connect to bulk or float",
            mres_info="Tuple with width, length, and layer of the mres between VSS and out<0>"
        )

    def design(self, w: int, l: int, res_type: str, nx: int, ny, nx_dum: int, ny_dum: int,
               top_vdd: bool, bot_vss: bool, sup_name: str, mres_info: Tuple[int, int, int]) -> None:

        self.top_vdd = top_vdd
        self.bot_vss = bot_vss

        nx_core = nx - nx_dum * 2
        ny_core = ny - ny_dum * 2
        ncore = nx_core * ny_core
        ndum = nx * ny - ncore

        # Design unit cell
        self.instances['XRES'].design(w=w, l=l, intent=res_type)

        # set up core and dummies
        self.array_instance('XRES', ['XRESC', 'XRES_DUM'], dx=0, dy=-200)

        # Array the core
        top_name = 'VDD' if top_vdd else 'top'
        self.rename_instance('XRESC', f'XRES<{ncore - 1}:0>', [('PLUS', f'{top_name},out<{ncore - 1}:1>'),
                                                               ('MINUS', f'out<{ncore - 1}:0>'), ('BULK', sup_name)])

        # Array the dummies
        self.rename_instance('XRES_DUM', f'XRES_DUM<{ndum - 1}:0>',
                             [('PLUS', sup_name), ('MINUS', sup_name), ('BULK', sup_name)])

        # Design metal resistors
        mres_w, mres_l, mres_layer = mres_info
        if self.tech_info.has_res_metal():
            self.instances['XMRES'].design(w=mres_w, l=mres_l, layer=mres_layer)
            self.reconnect_instance('XMRES', [('PLUS', 'out<0>'), ('MINUS', 'VSS' if bot_vss else 'bottom')])

            # Rename out
            self.rename_pin('out', f'out<{ncore - 1}:0>')
            self.has_idx0 = True
        else:
            self.remove_instance('XMRES')
            self.reconnect_instance_terminal(f'XRES<{ncore - 1}:0>', 'MINUS', f'out<{ncore - 1}:1>,VSS')
            self.rename_pin('out', f'out<{ncore - 1}:1>')
            self.has_idx0 = False

        if top_vdd:
            self.rename_pin('top', 'VDD')
        if bot_vss:
            self.rename_pin('bottom', 'VSS')

        # Change bulk pin name
        if (sup_name == 'VDD' and not top_vdd) or (sup_name == 'VSS' and not bot_vss):
            self.rename_pin('BULK', sup_name)
        else:
            self.remove_pin('BULK')
