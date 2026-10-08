"""
RIFE 4.25 (Practical-RIFE, https://github.com/hzwer/Practical-RIFE) - the flow network for inference only.
Copied from train_log/IFNet_HDv3.py and model/warplayer.py of the 4.25 release (2024-09-19), training parts left
out; the weights (flownet.pkl) are downloaded by download_models.py.

MIT License - Copyright (c) 2021 hzwer

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and
to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions
of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

_GRID = {}


def warp(ten_input, ten_flow):
    k = (str(ten_flow.device), str(ten_flow.dtype), str(ten_flow.size()))
    if k not in _GRID:
        hor = torch.linspace(-1.0, 1.0, ten_flow.shape[3], device=ten_flow.device, dtype=ten_flow.dtype).view(
            1, 1, 1, ten_flow.shape[3]).expand(ten_flow.shape[0], -1, ten_flow.shape[2], -1)
        ver = torch.linspace(-1.0, 1.0, ten_flow.shape[2], device=ten_flow.device, dtype=ten_flow.dtype).view(
            1, 1, ten_flow.shape[2], 1).expand(ten_flow.shape[0], -1, -1, ten_flow.shape[3])
        _GRID[k] = torch.cat([hor, ver], 1)
    ten_flow = torch.cat([ten_flow[:, 0:1, :, :] / ((ten_input.shape[3] - 1.0) / 2.0),
                          ten_flow[:, 1:2, :, :] / ((ten_input.shape[2] - 1.0) / 2.0)], 1)
    g = (_GRID[k] + ten_flow).permute(0, 2, 3, 1)
    return F.grid_sample(input=ten_input, grid=g, mode="bilinear", padding_mode="border", align_corners=True)


def conv(in_planes, out_planes, kernel_size=3, stride=1, padding=1, dilation=1):
    return nn.Sequential(
        nn.Conv2d(in_planes, out_planes, kernel_size=kernel_size, stride=stride, padding=padding,
                  dilation=dilation, bias=True),
        nn.LeakyReLU(0.2, True))


class Head(nn.Module):
    def __init__(self):
        super().__init__()
        self.cnn0 = nn.Conv2d(3, 16, 3, 2, 1)
        self.cnn1 = nn.Conv2d(16, 16, 3, 1, 1)
        self.cnn2 = nn.Conv2d(16, 16, 3, 1, 1)
        self.cnn3 = nn.ConvTranspose2d(16, 4, 4, 2, 1)
        self.relu = nn.LeakyReLU(0.2, True)

    def forward(self, x):
        x = self.relu(self.cnn0(x))
        x = self.relu(self.cnn1(x))
        x = self.relu(self.cnn2(x))
        return self.cnn3(x)


class ResConv(nn.Module):
    def __init__(self, c, dilation=1):
        super().__init__()
        self.conv = nn.Conv2d(c, c, 3, 1, dilation, dilation=dilation, groups=1)
        self.beta = nn.Parameter(torch.ones((1, c, 1, 1)), requires_grad=True)
        self.relu = nn.LeakyReLU(0.2, True)

    def forward(self, x):
        return self.relu(self.conv(x) * self.beta + x)


class IFBlock(nn.Module):
    def __init__(self, in_planes, c=64):
        super().__init__()
        self.conv0 = nn.Sequential(conv(in_planes, c // 2, 3, 2, 1), conv(c // 2, c, 3, 2, 1))
        self.convblock = nn.Sequential(*[ResConv(c) for _ in range(8)])
        self.lastconv = nn.Sequential(nn.ConvTranspose2d(c, 4 * 13, 4, 2, 1), nn.PixelShuffle(2))

    def forward(self, x, flow=None, scale=1):
        x = F.interpolate(x, scale_factor=1. / scale, mode="bilinear", align_corners=False)
        if flow is not None:
            flow = F.interpolate(flow, scale_factor=1. / scale, mode="bilinear", align_corners=False) * 1. / scale
            x = torch.cat((x, flow), 1)
        feat = self.conv0(x)
        feat = self.convblock(feat)
        tmp = self.lastconv(feat)
        tmp = F.interpolate(tmp, scale_factor=scale, mode="bilinear", align_corners=False)
        flow = tmp[:, :4] * scale
        mask = tmp[:, 4:5]
        feat = tmp[:, 5:]
        return flow, mask, feat


class IFNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.block0 = IFBlock(7 + 8, c=192)
        self.block1 = IFBlock(8 + 4 + 8 + 8, c=128)
        self.block2 = IFBlock(8 + 4 + 8 + 8, c=96)
        self.block3 = IFBlock(8 + 4 + 8 + 8, c=64)
        self.block4 = IFBlock(8 + 4 + 8 + 8, c=32)
        self.encode = Head()

    def forward(self, img0, img1, timestep=0.5, scale=1.0, f0=None, f1=None):
        """The frame `timestep` (0-1) of the way from img0 to img1 (N x 3 x H x W, 0-1, H and W multiples of 64).
        f0 / f1: the frames' encoder features when already computed (one pair, several timesteps)."""
        scale_list = [16 / scale, 8 / scale, 4 / scale, 2 / scale, 1 / scale]
        if not torch.is_tensor(timestep):
            timestep = (img0[:, :1].clone() * 0 + 1) * timestep
        else:
            timestep = timestep.repeat(1, 1, img0.shape[2], img0.shape[3])
        f0 = self.encode(img0[:, :3]) if f0 is None else f0
        f1 = self.encode(img1[:, :3]) if f1 is None else f1
        warped_img0, warped_img1 = img0, img1
        flow = mask = feat = None
        blocks = [self.block0, self.block1, self.block2, self.block3, self.block4]
        for i in range(5):
            if flow is None:
                flow, mask, feat = blocks[i](torch.cat((img0[:, :3], img1[:, :3], f0, f1, timestep), 1), None,
                                             scale=scale_list[i])
            else:
                wf0 = warp(f0, flow[:, :2])
                wf1 = warp(f1, flow[:, 2:4])
                fd, m0, feat = blocks[i](torch.cat((warped_img0[:, :3], warped_img1[:, :3], wf0, wf1, timestep, mask,
                                                    feat), 1), flow, scale=scale_list[i])
                mask = m0
                flow = flow + fd
            warped_img0 = warp(img0, flow[:, :2])
            warped_img1 = warp(img1, flow[:, 2:4])
        mask = torch.sigmoid(mask)
        return warped_img0 * mask + warped_img1 * (1 - mask)


def load(path: str, device="cuda") -> IFNet:
    """The 4.25 network with its weights (flownet.pkl; the "module." prefix of the DDP checkpoint stripped).
    Every weight the network needs must be in the file (strict)."""
    net = IFNet()
    state = torch.load(path, map_location="cpu", weights_only=True)
    state = {k.replace("module.", "", 1): v for k, v in state.items()}
    own = net.state_dict()
    missing = [k for k in own if k not in state]
    if missing:
        raise RuntimeError(f"RIFE weights miss {len(missing)} tensors (e.g. {missing[:3]})")
    net.load_state_dict({k: state[k] for k in own}, strict=True)
    return net.to(device).eval()
