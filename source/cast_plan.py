"""Validate the versioned preparation service response before scene changes."""
import io
import json
import math
import re
import zipfile


def read_cast_plan(response):
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or 'result.json' not in names:
            raise ValueError('Invalid preparation response')
        wire = json.loads(archive.read('result.json'))
        if isinstance(wire, dict) and set(wire) == {'v', 'p0', 'p1'} and wire.get('v') in (2, 3):
            plan = _decode_wire_plan(wire)
        elif isinstance(wire, dict) and set(wire) == {'version', 'items', 'auxiliary'}:
            plan = {'version': wire['version'], 'records': wire['items'],
                    'secondary': wire['auxiliary']}
        else:
            plan = wire
        if not isinstance(plan, dict) or set(plan) != {'version', 'records', 'secondary'} or type(plan.get('version')) is not int or plan['version'] not in (1, 2, 3):
            raise ValueError('Unsupported preparation response')
        expected = {'result.json'}
        for group in ('records', 'secondary'):
            specs = plan.get(group)
            if not isinstance(specs, list):
                raise ValueError('Invalid preparation parts')
            for spec in specs:
                fields = {'minimum', 'maximum', 'reference'}
                if group == 'records':
                    if plan['version'] == 3:
                        fields.update(('area', 'vertices', 'faces'))
                    else:
                        fields.add('surface' if plan['version'] == 1 else 'crop')
                if not isinstance(spec, dict) or set(spec) != fields:
                    raise ValueError('Unexpected preparation fields')
                for field in ('minimum', 'maximum', 'reference'):
                    _point(spec[field])
                if any(a > b for a,b in zip(spec['minimum'], spec['maximum'])):
                    raise ValueError('Invalid preparation bounds')
                if group == 'records':
                    if plan['version'] == 3:
                        _mesh_record(spec)
                        continue
                    if plan['version'] == 2:
                        _crop(spec['crop'])
                        continue
                    name = spec['surface']
                    if not isinstance(name, str) or not re.fullmatch(r'output_mesh_[0-9]{3,}', name) or name+'.ply' in expected:
                        raise ValueError('Invalid preparation surface')
                    expected.add(name+'.ply')
        if set(names) != expected:
            raise ValueError('Unexpected preparation output')
        return plan


def _decode_wire_plan(wire):
    version = wire['v']
    def decode(values, primary):
        output = []
        for value in values:
            if not isinstance(value, list) or len(value) != (6 if primary and version == 3 else 4 if primary else 3):
                raise ValueError('Invalid preparation record')
            spec = {'minimum': value[0], 'maximum': value[1], 'reference': value[2]}
            if primary:
                if version == 3:
                    spec.update(area=value[3], vertices=value[4], faces=value[5])
                else:
                    crop = value[3]
                    if not isinstance(crop, list) or len(crop) != 4:
                        raise ValueError('Invalid preparation record')
                    spec['crop'] = dict(zip(('center', 'radius', 'half_height', 'segments'), crop))
            output.append(spec)
        return output
    return {'version': version, 'records': decode(wire['p0'], True),
            'secondary': decode(wire['p1'], False)}


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError('Invalid preparation coordinate')


def _crop(value):
    if not isinstance(value, dict) or set(value) != {'center', 'radius', 'half_height', 'segments'}:
        raise ValueError('Invalid preparation crop')
    _point(value['center'])
    for key in ('radius', 'half_height'):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or value[key] <= 0:
            raise ValueError('Invalid preparation crop dimension')
    if type(value['segments']) is not int or not 3 <= value['segments'] <= 256:
        raise ValueError('Invalid preparation crop segments')


def _mesh_record(spec):
    area = spec['area']
    if type(area) not in (int, float) or not math.isfinite(area) or area <= 0:
        raise ValueError('Invalid preparation area')
    vertices, faces = spec['vertices'], spec['faces']
    if not isinstance(vertices, list) or len(vertices) < 3:
        raise ValueError('Invalid preparation vertices')
    for point in vertices:
        _point(point)
    if not isinstance(faces, list) or not faces:
        raise ValueError('Invalid preparation faces')
    for face in faces:
        if not isinstance(face, list) or len(face) != 3 or any(type(i) is not int or not 0 <= i < len(vertices) for i in face):
            raise ValueError('Invalid preparation triangle')
