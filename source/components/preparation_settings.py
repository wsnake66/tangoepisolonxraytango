# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Protected preparation configuration and compatibility registration."""

import bpy


def setting_keys():
    return ("slip_casting_min_loop_area",)


def register(property_factory):
    bpy.types.Scene.slip_casting_min_loop_area = property_factory(
        name="Preparation Detail",
        description="Internal preparation parameter",
        default=0.0,
        min=0.0,
        soft_max=1000.0,
        precision=2,
        options={"HIDDEN"},
    )

