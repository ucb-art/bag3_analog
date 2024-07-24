from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
# noinspection PyUnresolvedReferences,PyCompatibility
from builtins import *

from typing import Any, Set, Dict, Optional, Union, List, Tuple

from bag.layout.routing import TrackID, WireArray
from pybag.enum import RoundMode, MinLenMode, Orient2D, Direction

from bag.layout.template import TemplateDB
from bag.layout.util import BBox
from bag.util.math import HalfInt

from xbase.layout.mos.base import MOSBasePlaceInfo, MOSBase, TrackManager
from bag.layout.template import TemplateBase
import math


def via_maker(template, l1, l2, object, coordx, coordy, width):
    base = object
    layers = []
    width = [0]*l1+ width
    for i in range(l1, l2):
        if (i + 1) % 2 == 0:
            out_track = TrackID(i + 1, template.grid.coord_to_nearest_track(i + 1, coordy, half_track=True, mode=0,
                                                                            unit_mode=True), width=width[i])
        else:
            out_track = TrackID(i + 1, template.grid.coord_to_nearest_track(i + 1, coordx, half_track=True, mode=0,
                                                                            unit_mode=True), width=width[i])
        layers.append(template.connect_to_tracks([base], out_track, min_len_mode=0))
        base = layers[-1]

    return layers


def get_mos_conn_layer(self):
    return self.grid.tech_info.tech_params['layout']['mos_tech_class'].get_mos_conn_layer()


def max_conn_wires(self, tr_manager, wire_type, wire_list, start_coord=None, end_coord=None):
    max_coord, min_coord = 0, math.inf
    for w in wire_list:
        max_coord = max_coord if max_coord > w.upper else w.upper
        min_coord = min_coord if min_coord < w.lower else w.lower

    start_coord = start_coord if start_coord is not None else min_coord
    end_coord = end_coord if end_coord is not None else max_coord
    if end_coord < start_coord:
        raise ValueError("[Util Error:] End points smaller than start point, please check")
    conn_layer = wire_list[0].layer_id+1
    conn_w = tr_manager.get_width(conn_layer, wire_type)
    cur_tidx = self.grid.coord_to_track(conn_layer, start_coord, mode=RoundMode.NEAREST)
    res_wire_list = []
    while self.grid.track_to_coord(conn_layer, cur_tidx) <= end_coord:
        res_wire_list.append(self.connect_to_tracks(wire_list, TrackID(conn_layer, cur_tidx, conn_w)))
        cur_tidx = tr_manager.get_next_track(conn_layer, cur_tidx, wire_type, wire_type)
    if len(res_wire_list) < 1:
        raise ValueError("[Util Error:] Targeted connection have no effect")
    return res_wire_list


def round_to_blk_pitch(x_loc, y_loc, blk_w, blk_h):
    return (math.ceil(x_loc / blk_w) * blk_w, math.ceil(y_loc / blk_h) * blk_h)


def draw_stack_wire(self: TemplateBase, wire: WireArray, top_layid: int, x0: Optional[Union[int, float]] = None,
                    y0: Optional[Union[int, float]] = None, x1: Optional[Union[int, float]] = None,
                    y1: Optional[Union[int, float]] = None, tr_list: Optional[List[Union[int, float]]] = None,
                    sp_list: Optional[List[Union[HalfInt, int]]] = None, max_mode: bool = True,
                    min_len_mode: MinLenMode = MinLenMode.NONE,
                    mode: int = 1, sep_margin: bool = False,
                    sp_margin_list: Optional[List[Union[HalfInt, int]]] = None) -> List[List[WireArray]]:
    """
        create WireArray from bot_layid to top_layid-1 within the given coordinates
    Parameters
    ----------
    self: TemplateBase
        template database.
    wire: WireArray
        wire to be connected.
    top_layid: Int
        top layer id.
    x0: Union[Int, float]
        bottom left, x coordinate.
    y0: Union[Int, float]
        bottom left, y coordinate.
    x1: Union[Int, float]
        top right, x coordinate.
    y1: Union[Int, float]
        top right, y coordinate.
    x_mode: Int
        x direction mode.
        If negative, the result wire will have width less than or equal to the given width.
        If positive, the result wire will have width greater than or equal to the given width.
    y_mode: Int
        y direction mode.
        If negative, the result wire will have width less than or equal to the given width.
        If positive, the result wire will have width greater than or equal to the given width.
    half_track: Bool
        True to get half track.
    tr_list: List[Union[Int, float]]
        Wire array track list.
    sp_list: List[Union[HalfInt]]
        Wire array track separation list.
    max_mode: Bool
        True to draw wire with max width from coordinates and tr_list
    track_mode:
        #######
    min_len_mode: Int
        Mininum length mode. See connect_to_tracks for details.
    mode: Int
        draw stack mode.
    Returns
    -------
    wire_arr_list: List[WireArray]
        stack wire list.
    """
    bot_layid = wire.layer_id
    # get wire layer
    if top_layid > bot_layid:
        layer_flip = False
    else:
        layer_flip = True

    if tr_list is not None:
        if len(tr_list) != top_layid - bot_layid:
            raise ValueError('If given tr_list, its length should same as layers(top_layid-bot_layid)')

    # get coordinate
    if x0 is None:
        x0 = wire.bound_box.xl
    if y0 is None:
        y0 = wire.bound_box.yl
    if x1 is None:
        x1 = wire.bound_box.xh
    if y1 is None:
        y1 = wire.bound_box.yh

    # check coordinates
    if x1 <= x0 or y1 <= y0:
        raise ValueError("If given coordinates,"
                         "we need left coord smaller than right coordinate\n"
                         "and bottom coordinate smaller than top coordinate")
    if bot_layid == top_layid:
        raise ValueError("Need top_layer != wire layer. It can be larger or smaller than it.")

    # draw stack wires
    wire_arr_list = [wire]
    if not layer_flip:
        swp_list = list(range(bot_layid, top_layid))
    else:
        swp_list = list(range(top_layid, bot_layid))[::-1]

    for i in swp_list:
        if self.grid.get_direction(i + 1) == Orient2D.y:
            if mode == 0:
                tr, tr_w = self.grid.interval_to_track(i + 1, (x0, x1))
                if tr_w is None:
                    tr_w = 1
                # could specify tr from outside and choose the larger one
                if tr_list is not None:
                    if tr_list[i - bot_layid] is not None:
                        if max_mode:
                            tr_w = max(tr_w, tr_list[i - bot_layid])
                        else:
                            tr_w = tr_list[i - bot_layid]

                tr_tid = TrackID(i + 1, tr, width=tr_w)
                wire_n = self.connect_to_tracks(wire_arr_list[-1], tr_tid, track_lower=y0, track_upper=y1,
                                                min_len_mode=min_len_mode)
            elif mode == 1:
                # get wire width and space
                if tr_list is not None:
                    w_ntr = tr_list[i - bot_layid]
                else:
                    w_ntr = wire.bound_box.w
                if sp_list is not None:
                    sp_ntr = sp_list[i - bot_layid]
                else:
                    sp_ntr = self.grid.get_sep_tracks(i + 1, ntr1=w_ntr, ntr2=w_ntr)
                if sp_margin_list is not None:
                    sp_margin_ntr = sp_margin_list[i - bot_layid]
                else:
                    sp_margin_ntr = sp_ntr // 2
                tid_lower = self.grid.coord_to_track(i + 1, x0, mode=RoundMode.GREATER_EQ)
                tid_upper = self.grid.coord_to_track(i + 1, x1, mode=RoundMode.LESS_EQ)
                if tid_lower == tid_upper:
                    tr_idx = [tid_upper]
                else:
                    tr_idx = self.get_available_tracks(i + 1, tid_lower, tid_upper, y0 - 170, y1 + 170, w_ntr, sep=sp_ntr,
                                                       sep_margin=sp_margin_ntr if sep_margin else None)
                    if tid_upper - tid_lower < w_ntr and len(tr_idx) > 0:
                        tr_idx = [(tid_upper + tid_lower) / 2]
                wire_n = []
                for idx in tr_idx:
                    tr_tid = TrackID(i + 1, idx, width=w_ntr)
                    wire_n.append(self.connect_to_tracks(wire_arr_list[-1], tr_tid, min_len_mode=min_len_mode))
            else:
                raise ValueError("For now, only support two modes.")
        else:
            if mode == 0:
                tr, tr_w = self.grid.interval_to_track(i + 1, (y0, y1))
                if tr_w is None:
                    tr_w = 1
                # could specify tr from outside and choose the larger one
                if tr_list is not None:
                    if tr_list[i - bot_layid] is not None:
                        if max_mode:
                            tr_w = max(tr_w, tr_list[i - bot_layid])
                        else:
                            tr_w = tr_list[i - bot_layid]
                tr_tid = TrackID(i + 1, tr, width=tr_w)
                wire_n = self.connect_to_tracks(wire_arr_list[-1], tr_tid, track_lower=x0, track_upper=x1,
                                                min_len_mode=min_len_mode)
            elif mode == 1:
                # get wire width and space
                if tr_list is not None:
                    w_ntr = tr_list[i - bot_layid]
                else:
                    w_ntr = wire.bound_box.w
                if sp_list is not None:
                    sp_ntr = sp_list[i - bot_layid]
                else:
                    sp_ntr = self.grid.get_sep_tracks(i + 1, ntr1=w_ntr, ntr2=w_ntr)
                if sp_margin_list is not None:
                    sp_margin_ntr = sp_margin_list[i - bot_layid]
                else:
                    sp_margin_ntr = sp_ntr // 2
                tid_lower = self.grid.coord_to_track(i + 1, y0, mode=RoundMode.GREATER_EQ)
                tid_upper = self.grid.coord_to_track(i + 1, y1, mode=RoundMode.LESS_EQ)
                if tid_upper == tid_lower:
                    tr_idx = [tid_lower]
                else:
                    tr_idx = self.get_available_tracks(i + 1, tid_lower, tid_upper, x0 - 150, x1 + 150, w_ntr, sep=sp_ntr,
                                                       sep_margin=sp_margin_ntr if sep_margin else None)
                    if tid_upper - tid_lower < w_ntr and len(tr_idx) > 0:
                        tr_idx = [(tid_upper + tid_lower) / 2]


                wire_n = []
                for idx in tr_idx:
                    tr_tid = TrackID(i + 1, idx, width=w_ntr)
                    wire_n.append(self.connect_to_tracks(wire_arr_list[-1], tr_tid, min_len_mode=min_len_mode, track_lower=x0, track_upper=x1))
            else:
                raise ValueError("For now, only support two modes.")

        wire_arr_list.append(wire_n)

    return wire_arr_list



def draw_multiple_stack_wire(self: TemplateBase, tr_manager, warr_list: List[WireArray], top_layid: int, wire_type: str,
                             sep_type: (str, str), y0=None, y1=None, x0=None, x1=None, stack_idx=-1):

    stack_wire = []
    cur_lay = warr_list[0].layer_id
    layer_range = range(cur_lay + 1, top_layid + 1)
    for warr in warr_list:
        stack = draw_stack_wire(self, warr, top_layid, x0=x0, x1=x1, y0=y0, y1=y1,
                                tr_list=[tr_manager.get_width(lay, wire_type) for lay in layer_range],
                                sp_list=[tr_manager.get_sep(lay, sep_type) for lay in layer_range])
        stack_wire += stack[stack_idx]
    return stack_wire


def extend_matching_wires(self, warrs: List[WireArray], lower: Optional[Union[int, float]]=None,
                          upper: Optional[Union[int, float]]=None)-> List[WireArray]:

    warr_lower = lower if lower!=None else warrs[0].lower
    warr_upper = upper if upper!=None else warrs[0].upper

    lay_id = warrs[0].layer_id
    width = warrs[0].track_id.width
    warr_lower = warr_lower if warrs[0].lower > warr_lower else warrs[0].lower
    warr_upper = warr_upper if warrs[0].upper < warr_upper else warrs[0].upper

    for warr in warrs[1:]:
        # inspect layer id
        assert lay_id == warr.layer_id
        # find max width
        width = warr.track_id.width if width < warr.track_id.width else width
        # find min lower
        warr_lower = warr_lower if warr.lower > warr_lower else warr.lower
        # find max upper
        warr_upper = warr_upper if warr.upper < warr_upper else warr.upper

    extended_warrs = []
    for warr in warrs:
        new_warr = self.add_wires(lay_id, warr.track_id.base_index, warr_lower, warr_upper, width=width)
        extended_warrs.append(new_warr)

    return extended_warrs

def power_fill_helper(self, layer_id: int, tr_manager: TrackManager,
                          vdd_warrs: List[WireArray], vss_warrs: List[WireArray], bbox_overwrite=False,
                          bound_box: Optional[BBox] = None, top_wire: Optional[WireArray] = None,
                          bot_wire: Optional[WireArray] = None, left_wire: Optional[WireArray] = None,
                          right_wire: Optional[WireArray] = None, **kwargs) -> Tuple[List[WireArray], List[WireArray]]:
        """Calculate via extention to do power fill.
        Parameters
        ----------
        layer_id: int
            the layer to draw power lines
        vdd_warrs: List[WireArray]
            vdd wires (layer_id-1) to be connected. [] if no vdd wires
        vss_warrs: List[WireArray]
            vss wires (layer_id-1) to be connected. [] if no vss wires
        bbox_overwrite: bool
            True to overwrite with bound_box
        bound_box: Optional[BBox]
            The region to draw power lines
            (takes the largest margin among bound_box and vdd_warrs/vss_warrs in layer_id direction
             takes the smallest margin among bound_box and vdd_warrs/vss_warrs in layer_id-1 direction)
        top_wire: Optional[WireArray]
            The topmost wire in among vss_warrs/vdd_warrs if not specified, the last element in vdd_warrs or vss_warrs
            would be assigned if vdd_warrs + vss_warrs is even or odd
         bot_wire: Optional[WireArray]
            The bottommost wire in among vss_warrs/vdd_warrs if not specified, the first element in vss_warrs or
            vdd_warrs (if vss_warrs = [])
        left_wire: Optional[WireArray]
            The leftmost wire in among vss_warrs/vdd_warrs if not specified, the first element in vss_warrs or
            vdd_warrs (if vss_warrs = [])
        right_wire: Optional[WireArray]
            The rightmost wire in among vss_warrs/vdd_warrs if not specified, the last element in vdd_warrss or vss_warrs
            would be assigned if vdd_warrs + vss_warrs is even or odd

         Returns
        -------
        (vdd, vss) : Tuple[List[WireArray], List[WireArray]]
            list of created wires on layer_id

        """
        sup_w = tr_manager.get_width(layer_id, 'sup')
        sup_w_lower = tr_manager.get_width(layer_id - 1, 'sup')
        wl, wh = self.grid.get_wire_bounds(layer_id, 0, width=sup_w)
        w_mid = int((wh - wl) / 2)
        via_ext_lower, via_ext_cur = self.grid.get_via_extensions(Direction.LOWER, layer_id - 1, sup_w_lower, sup_w)

        is_horizontal = (self.grid.get_direction(layer_id) == 0)
        num_vss = len(vss_warrs)
        num_vdd = len(vdd_warrs)
        if num_vdd + num_vss == 0:
            raise ValueError("need at least vss_warrs or vdd_wars")

        top_wire, bot_wire, left_wire, right_wire = get_boundary_wires(self, vdd_warrs + vss_warrs)
        # if not top_wire:
        #     top_wire = vss_warrs[-1] if ((num_vss + num_vdd) & 1) and (num_vss > 0) else vdd_warrs[-1]
        # if not bot_wire:
        #     bot_wire = vss_warrs[0] if num_vss > 0 else vdd_warrs[0]
        # if not right_wire:
        #     right_wire = vss_warrs[-1] if ((num_vss + num_vdd) & 1) and (num_vss > 0) else vdd_warrs[-1]
        # if not left_wire:
        #     left_wire = vss_warrs[0] if num_vss > 0 else vdd_warrs[0]
        # layer_id is horizontal
        if is_horizontal:
            dx = via_ext_cur
            dy = - via_ext_lower - w_mid

        # layer_id is vertical
        else:
            dx = - via_ext_lower - w_mid
            dy = via_ext_cur
        xl, xh, yl, yh = left_wire.bound_box.xl, right_wire.bound_box.xh,  bot_wire.bound_box.yl, top_wire.bound_box.yh
        xl = xl if is_horizontal else xl - dx
        xh = xh if is_horizontal else xh + dx
        yl = yl if not is_horizontal else yl - dy
        yh = yh if not is_horizontal else yh + dy

        xl = bound_box.xl if (bound_box and ((bound_box.xl < xl) or bbox_overwrite)) else xl
        xh = bound_box.xh if (bound_box and ((bound_box.xh > xh) or bbox_overwrite)) else xh
        yl = bound_box.yl if (
                    bound_box and ((bound_box.yl < yl) or bbox_overwrite)) else yl
        yh = bound_box.yh if (
                    bound_box and ((bound_box.yh > yh) or bbox_overwrite)) else yh
        # bb = bound_box.expand(dy=dy, dx=dx)
        bb = BBox(xl=xl, yl=yl, xh=xh, yh=yh)
        if num_vss == 0:
            sup_type = 'vdd'
        elif num_vdd == 0:
            sup_type = 'vss'
        else:
            sup_type = 'both'
        vdd, vss = self.do_power_fill(layer_id, tr_manager, vdd_warrs, vss_warrs, bound_box=bb, sup_type=sup_type,
                                      **kwargs)
        return vdd, vss


def get_boundary_wires(self, warrs: List[WireArray]) -> Tuple[WireArray, WireArray, WireArray, WireArray]:
    # return topmost, bottommost, leftmost, and rightmost wire in a list of wires
    # initialize
    wire_top, wire_bot, wire_left, wire_right = [warrs[0]] * 4
    for wire in warrs:
        if wire.bound_box.yh > wire_top.bound_box.yh:
            wire_top = wire
        if wire.bound_box.yl < wire_bot.bound_box.yl:
            wire_bot = wire
        if wire.bound_box.xl < wire_left.bound_box.xl:
            wire_left = wire
        if wire.bound_box.xh > wire_right.bound_box.xh:
            wire_right = wire

    return wire_top, wire_bot, wire_left, wire_right
