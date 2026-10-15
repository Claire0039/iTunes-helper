# -*- coding: utf-8 -*-
"""
ncm_glyphs.py —— 播放器控件图标（自动生成，勿手改）

由 make_player_icons.py 从 icon-src/*.png 生成。
每个图标都是「白色图形 + alpha」的 PNG，运行期按主题色染色，
所以浅色 / 深色主题共用同一份素材。
"""

import base64

GLYPHS = {
    "prev": (
        "iVBORw0KGgoAAAANSUhEUgAAACUAAAAWCAYAAABHcFUAAAAACXBIWXMAAA7EAAAOxAGVKw4bAAABTUlEQVRIx83UIUgDYRTA"
        "8f87PsGgbYJgtNgMEyw2w4rJYDxhxSgYFOwWYcE149kMNgWD1TbBYLELBg2Ca4Zn8E3O4R13977BXtzufvy/t9uBc1R1oD/T"
        "cTptc9SDpPp3zh3WUx4KDYAl4IUIo6oHQG/881ATyYA0Qswq8Fj0fVIR2bbfOkbQXVlQpU2p6hvQihCTAlmVa5MS5MS2UzUo"
        "FDjBnKzqAZJ/kGVDjiNs5wz4qntfGENugU6EmDYwaHp/YkjXtuMJGo5epp4gAFHVT2COKRpxvdYnNAnwPnVRIrIA7Eaw+iIi"
        "wH2MTSEiFwbeOKyWWRvAmjvq9wET2QJW3A+qyIMdsu+OMvDZwNMIcfvAvDsqBx4BM8CHM2xoh9ybyL9CVa+1eC5rOJsljjYJ"
        "Wy+wrhpYvShROfDQG2XOoqq+RokycDYHdp3WzijqG80IUQOgZfs5AAAAAElFTkSuQmCC"
    ),
    "play": (
        "iVBORw0KGgoAAAANSUhEUgAAACIAAAAnCAYAAABqippxAAAACXBIWXMAAA7EAAAOxAGVKw4bAAABQ0lEQVRYw82YsUoDQRRF"
        "75UIsdNOST7AQrC0sRAUtAh+RJp0NhZ2Qj7CMkUKC0uLQISkyB+ksLVz66QIuBDhWmQDukzADLPz5pQLA4e5bx5vHySdacUU"
        "lkia6S93ViKbOE1FRJLeJdVTEFnzlIrImtuqPChJHud2SX6HFNnxPLeU9GwZTWVx+Ubjokkyix2Ni09JwxREAOC6iOvRMhoX"
        "VyTHKYgAQEayGTsaF43/dOcYN1LmhuRbCiIAkAM4IjmPGY2LOoCZpL71jZTppCJiFk2yIi1rkQeuGNSMBAYkW78/xBaZF/0j"
        "t6yRC5IHLolYIvdFHUyqHhU30Ys9s5YZSdrf9tpCFmsO4ITkh2VDOye55ysRIppwmwNPgZfQT2vbGskAHJNcWP6EX1pvA9rW"
        "+5Gu9cbo1achhRBpFwJfkg6tBpMf/8798jI65zYAAAAASUVORK5CYII="
    ),
    "next": (
        "iVBORw0KGgoAAAANSUhEUgAAACUAAAAXCAYAAACMLIalAAAACXBIWXMAAA7EAAAOxAGVKw4bAAABTklEQVRIx82Xr0sDYRzG"
        "n2dcsBgGDgSjxWZQ8A9YWDEZjBM02AwGhXWLsOCatsWFNQWD1SI7MBiNgkGDyJrCY/B92Tm4c7fvd7BPOu7g4fP+uPeeg0Zs"
        "wICkRsgZwIr+8mTIuRzLanpJRY4dpCIrZbMqOffbIXAddl4kdT2kIo+S7hzEmmGQOx5SAFA375ERfUlvHlKRbpBLcp4nE+Ys"
        "hZwzD6nIl6QLh1lrBblVDykAOPI42wLPkm49pCIDSQ/h+tOQ08juW0oS5ovhPEqZl28WvHtI3ZMkgI5D1h7JWmIM2SSZxvPH"
        "kHNDctu6fB3+kjrMzlpWqMwpnGWR5NBB5pzkqeXTAACHJK8cZD4A1Eh+W96+NCzVf0KTDPCAZLVIqKjkReolSl6vIOfao3m2"
        "p2ie/ZysLWsdfpW0PGWtHpc68ejou8YfkP3MwBYsWT81NYwItMiXmgAAAABJRU5ErkJggg=="
    ),
    "shuffle": (
        "iVBORw0KGgoAAAANSUhEUgAAACQAAAAXCAYAAABj7u2bAAAACXBIWXMAAA7EAAAOxAGVKw4bAAABa0lEQVRIx82XL0/DYBDG"
        "75KKORBLEAjExAQCgRjJxAQCMTISBAKxj4FALJmY5CMgkMgtkFROIhBIxEggWYKYGAk4SH6YNjSXt+val6R9kibt/evT6931"
        "KlICgFtgKFUBf5hVjVCMXqzTyKApIoHx+1LVN88b10Vky4hrIvLoMJ+o6omLrcU7cJmDxBHwREFITvuDDDIT/LBICxwADeAC"
        "+DZOZyk+NivXQAfYjI5gRQ0BjPLUwr5x7hr9NKEbFyjq7SIFWjNBdiP5XUIW5uyysW+7Ngyp18T5PEecAXD6XzOk40j5Z9mD"
        "bWEIHZZJxpWhZVlkbA3NC9bQEDj3JbNhyLQieejRZWFRMl1Dpm/0D55zqJnlEAB7wMjh3F9zUt8A7XhSm9guXK0a42loZzxI"
        "6PktW65DaAEMcrzeHjAryijeh1qO2B8i8qKqPx6NsCMi9egySOxDU4f5vaoeV2Vj7FZlhX2uyk6d+tfxC8O9C6GmIqPQAAAA"
        "AElFTkSuQmCC"
    ),
    "repeat": (
        "iVBORw0KGgoAAAANSUhEUgAAACEAAAAZCAYAAAC/zUevAAAACXBIWXMAAA7EAAAOxAGVKw4bAAABBElEQVRIx+2WLQ7CQBSE"
        "Zwk4HAbOUIHBITgAN0AgkBU1nACJIUEiMSSIIggkCARX4AZIOAECksG0YbtZ6E/6sqaf29fJ7iQ7720BIfilD1cwydaFgTbt"
        "NLNu4JEMKcckzcCN8pzNc5V+h8a3I4ArgEe0fue4kT6AkaW+UEpNs4RoJRBMkvT+iX1NOBfojlMW8TNWC7ToKK9j3+VQCUhe"
        "UFFhDCtHebwA2Lk04OcaDSTHQnOEJF9ZxIeyhxnJmWYiSHvSE5RkYGXuWf8hXAIILPV19LLmpQWgC2Bo1BvW7ogSOxDO5V0p"
        "1YkXNYtgI3j4HkBPN1DkH9Fz0cth2cEsamQobeID0U4O7gHb/aoAAAAASUVORK5CYII="
    ),
}


def glyph_bytes(name):
    """返回图标的 PNG 原始字节；没有这个图标时返回 None。"""
    data = GLYPHS.get(name)
    if not data:
        return None
    if isinstance(data, (tuple, list)):
        data = "".join(data)
    try:
        return base64.b64decode(data)
    except Exception:
        return None
