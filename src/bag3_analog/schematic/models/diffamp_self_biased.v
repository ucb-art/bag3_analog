// SPDX-License-Identifier: Apache-2.0
// Copyright 2020 Blue Cheetah Analog Design Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

{{ _header }}

parameter DELAY = {{ delay | default(0, true) }};
logic temp;

always_comb begin
    casez ({v_inp, v_inn, VDD, VSS})
        4'b1010: temp = 1'b1;
        4'b0110: temp = 1'b0;
        4'b??00: temp = 1'b0;
        default: temp = 1'bx;
    endcase
end

assign #DELAY v_out = temp;

endmodule