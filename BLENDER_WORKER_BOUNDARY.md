# Moldboxer Blender integration and external Worker boundary

Copyright (C) 2026 MOLDBOXER, S.L. All rights reserved. This document may be
shared for license-compliance review; it does not grant rights in Moldboxer
software or implementation.

Document date: 24 August 2026
Prepared by: MOLDBOXER, S.L.

## Purpose

This note gives Blender Foundation and other license reviewers a concise,
external-facing description of the boundary between Blender, the Moldboxer
Blender add-on, the proprietary Moldboxer Worker, and Moldboxer's remote
service. It intentionally describes only the facts needed for license review.
It does not disclose Moldboxer algorithms, operation details, network
endpoints, data formats, security mechanisms, or other product implementation.

## Short explanation

The code that runs inside Blender and uses Blender's Python API is licensed
under GPL-3.0-or-later. The proprietary Moldboxer Worker is a separate program:
it is launched as a separate operating-system process, is not imported into
Blender, contains no Blender source code, and does not import, call, or link to
Blender APIs. The GPL add-on and Worker exchange implementation-neutral data
across the process boundary. The Worker may also communicate with a Moldboxer
service through an authenticated network boundary. The service is not loaded
into Blender and its code is not distributed as part of the Blender add-on.

```text
Blender process
┌──────────────────────────────────────────────┐
│ Blender                                      │
│   ↕ Blender Python API                       │
│ Moldboxer add-on, adapter and Worker client  │  GPL-3.0-or-later
└──────────────────────┬───────────────────────┘
                       │ data-only inter-process boundary
                       ▼
┌──────────────────────────────────────────────┐
│ Moldboxer Worker                             │  Commercial license
│ Separate operating-system process            │
│ No Blender source code or Blender API calls  │
└──────────────────────┬───────────────────────┘
                       │ authenticated network boundary, when required
                       ▼
┌──────────────────────────────────────────────┐
│ Moldboxer remote service                     │
│ Not loaded into or distributed with Blender  │
└──────────────────────────────────────────────┘
```

## Boundary facts

| Question | Moldboxer boundary |
| --- | --- |
| What runs inside Blender? | Only Blender-facing add-on code, UI, adapters, and the Worker-launching client. These files are GPL-3.0-or-later. |
| How does the Worker execute? | As a child operating-system process with its own process state and lifecycle. It is not a Python module loaded into Blender's process. |
| Does the Worker use Blender APIs? | No. Worker code does not import or call `bpy`, `bmesh`, `mathutils`, or another Blender API, and does not link to Blender. |
| What crosses the local boundary? | Data needed for the requested operation. Blender objects, Python objects, callbacks, code, and Blender API handles do not cross the boundary. |
| Does the Worker contain Blender code? | No Blender source code is copied into the Worker. Shared boundary definitions are separately available under the MIT License. |
| Why may Blender's Python executable appear in a process listing? | The current launcher may reuse Blender's bundled Python interpreter as a compatible generic Python runtime. The launcher can use an explicitly supplied compatible interpreter. Runtime selection does not load Blender or create Blender API calls in the Worker. |
| What is the server relationship? | The Worker may make authenticated requests to a remote Moldboxer service. This is a network service boundary, not an import, link, or in-process extension of Blender. No remote-service source code is delivered as part of the add-on. |
| What if the components share an installer? | Co-packaging is for installation convenience. The components retain separate licenses and execute across the boundaries described above. |

## Licensing position

Blender's official license guidance states that published scripts using the
Blender Python API must be GPL-compatible. Moldboxer follows that guidance by
licensing the complete Blender-facing add-on, including its adapters and Worker
client, under GPL-3.0-or-later.

Blender's official FAQ also distinguishes software that operates outside
Blender, uses no Blender source code or API calls, and produces data for Blender
to operate on. Based on the technical facts above, Moldboxer's position is that
the external Worker is a separate program and is not subject to Blender's GPL
merely because the GPL add-on launches it, exchanges data with it, or installs
it in the same product package.

Official Blender references:

- <https://www.blender.org/about/license/>
- <https://www.blender.org/support/faq/#gnu-general-public-license-gpl>

The remote service is a separate network system. Its internal implementation
is outside the scope of this document and is not relied upon to establish the
Worker's separation from Blender.

## How the boundary is maintained

Moldboxer maintains this separation through:

- file-level SPDX identifiers and an explicit component scope map;
- automated import checks that fail if Worker modules import Blender APIs;
- a separate-process launch boundary;
- data-only client and Worker interfaces;
- separate license documents for the GPL add-on, shared interface definitions,
  and proprietary Worker; and
- review whenever code, linking, imports, or execution behavior crosses the
  documented boundary.

If the Worker were changed to load inside Blender, import a Blender API, link to
Blender, or incorporate Blender source code, its classification would require a
new technical and legal review.

## Copy-ready response for Blender Foundation

> Moldboxer's Blender-facing add-on, including its UI, adapters, and external
> Worker client, is GPL-3.0-or-later. Our proprietary Worker is a separate
> operating-system process. It is not imported into Blender, contains no
> Blender source code, and does not import, call, or link to Blender APIs. The
> GPL client exchanges implementation-neutral data with the Worker across a
> process boundary, and the Worker may separately use an authenticated network
> service. Co-packaging is only for installation convenience; the components
> retain their separate licenses. We maintain automated checks against Blender
> API imports and can provide further boundary evidence privately if helpful.

This document records Moldboxer's technical architecture and licensing
position. It is not a substitute for advice from qualified counsel or a formal
determination by Blender Foundation.
