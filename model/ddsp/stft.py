import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.fft import rfft


class STFT(nn.Module):
    def __init__(
        self,
        n_fft: int = 2048,
        hop_length: int = 512,
        win_length: int = 2048,
        window: torch.Tensor = None,
        center: bool = True,
    ):
        super().__init__()

        self.n_fft = n_fft
        self.hop_length = hop_length
        self.win_length = win_length
        self.window = window
        self.center = center
        self.pad_amount = self.n_fft // 2

        en_k = torch.eye(self.n_fft)[:, None, :]
        tmp = rfft(torch.eye(self.n_fft))
        fft_k = torch.stack([tmp.real, tmp.imag], dim=2)
        fft_k = torch.cat((fft_k[:, :, 0], fft_k[:, :, 1]), dim=1)
        ifft_k = torch.pinverse(fft_k)[:, None, :]

        left_pad = (self.n_fft - self.win_length) // 2
        right_pad = left_pad + (self.n_fft - self.win_length) % 2
        window = F.pad(window, (left_pad, right_pad))
        padded_window = window**2

        fft_k = fft_k.T * window
        ifft_k = ifft_k * window
        ola_k = torch.eye(self.n_fft)[:, None, : self.n_fft]

        self.register_buffer("ola_k", ola_k)
        self.register_buffer("en_k", en_k)
        self.register_buffer("fft_k", fft_k)
        self.register_buffer("ifft_k", ifft_k)
        self.register_buffer("padded_window", padded_window[None, :, None])

        self.e8 = torch.tensor(1e-8)

    def stft(self, x):
        if x.dim() == 2:
            x = x.unsqueeze(1)

        if self.center:
            x = F.pad(x, (self.pad_amount, self.pad_amount), mode="reflect")

        x = F.conv1d(x, self.en_k, stride=self.hop_length)
        x = x.transpose(1, 2)
        x = F.linear(x, self.fft_k)
        x = x.transpose(1, 2)
        dim = self.n_fft // 2 + 1
        real = x[:, :dim, :]
        imag = x[:, dim:, :]

        return real, imag

    def istft(self, real, imag, length: int):
        x = torch.cat((real, imag), dim=1)
        frames = x.size(-1)
        x = F.conv_transpose1d(x, self.ifft_k, stride=self.hop_length)

        t = self.padded_window.repeat(1, 1, frames)
        # t = t.to(x)

        coff = F.conv_transpose1d(t, self.ola_k, stride=self.hop_length)
        end = self.pad_amount + length
        x = x[..., self.pad_amount : end]
        coff = coff[..., self.pad_amount : end]
        coff = torch.where(coff > self.e8, coff, self.e8)
        x = x / coff

        return x.squeeze(1)
