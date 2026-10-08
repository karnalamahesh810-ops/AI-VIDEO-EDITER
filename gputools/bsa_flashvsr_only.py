"""
Block-Sparse-Attention (BSD-3, mit-han-lab) built for FlashVSR alone: the one kernel FlashVSR calls (forward,
bf16, head dim 128, not causal - Wan2.1-1.3B: 12 heads x 128, bf16 pipeline). Every other source leaves setup.py
(one kernel instead of 24: minutes instead of most of an hour, and a build that fits a 16 GB machine), and the
dispatchers answer anything else with an error instead of a kernel that is not there. Run inside the checkout,
before `python setup.py bdist_wheel`; safe to run twice.
"""
import io
import re

KEEP = "csrc/block_sparse_attn/src/flash_fwd_block_hdim128_bf16_sm80.cu"

setup = io.open("setup.py", encoding="utf-8").read()
lines = []
for line in setup.split("\n"):
    m = re.search(r'"(csrc/block_sparse_attn/src/flash_(?:fwd|bwd)_block_[^"]+\.cu)"', line)
    if m and m.group(1) != KEEP:
        continue
    lines.append(line)
setup2 = "\n".join(lines)
assert KEEP in setup2, "FlashVSR's kernel is not in setup.py"
io.open("setup.py", "w", encoding="utf-8").write(setup2)

api_path = "csrc/block_sparse_attn/flash_api.cpp"
api = io.open(api_path, encoding="utf-8").read()
fwd_old = """    FP16_SWITCH(!params.is_bf16, [&] {
        HEADDIM_SWITCH(params.d, [&] {
            BOOL_SWITCH(params.is_causal, Is_causal, [&] {
                run_mha_fwd_block_<elem_type, kHeadDim, Is_causal>(params, stream);
            });
        });
    });"""
fwd_new = """    TORCH_CHECK(params.is_bf16 && params.d > 64 && params.d <= 128 && !params.is_causal,
                "block_sparse_attn: this build has FlashVSR's kernel only (bf16, head dim 128, not causal)");
    run_mha_fwd_block_<cutlass::bfloat16_t, 128, false>(params, stream);"""
bwd_old = "run_mha_bwd_block_<elem_type, kHeadDim, Is_causal>(params, stream);"
bwd_new = 'TORCH_CHECK(false, "block_sparse_attn: backward kernels are not built (inference image)");'
if fwd_old in api:
    api = api.replace(fwd_old, fwd_new)
assert fwd_new in api, "forward dispatch not found"
if bwd_old in api:
    api = api.replace(bwd_old, bwd_new)
assert bwd_new in api, "backward dispatch not found"
io.open(api_path, "w", encoding="utf-8").write(api)
print("Block-Sparse-Attention: FlashVSR's kernel only (fwd, bf16, hdim 128, non-causal)")
