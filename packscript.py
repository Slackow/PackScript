#!/usr/bin/env python3

# /// script
# requires-python = ">=3.12"
# ///
__version__ = '0.3.0'
__v_type__  = 'dev'
__author__  = 'Slackow'
__license__ = 'MIT'


# # # # # # # # # # # # # # # # # # # # # #
# Please set this to your username if you are modifying this script
modified_by = ''
# # # # # # # # # # # # # # # # # # # # # #

import argparse, json, os, re, sys, shutil, tempfile, textwrap
from contextlib import contextmanager
from typing import overload, Never
from pathlib import Path


PF = int | tuple[int, int]
def ver(base_version: str, start: int, end: int, *, pf: PF):
    return {f'{base_version}.{x}': pf for x in range(start, end + 1)}


pack_formats: dict[str, PF] = {
    'future': (9001, 0),
    '26.3': (122, 0), '26.2': (107, 1),
    '26.1.2': (101, 1), '26.1.1': (101, 1), '26.1': (101, 1),
    '1.21.11': (94, 1),
    '1.21.10': (88, 0), '1.21.9': (88, 0),
    '1.21.8': 81, '1.21.7': 81,
    '1.21.6': 80,
    '1.21.5': 71,
    '1.21.4': 61,
    '1.21.3': 57, '1.21.2': 57,
    '1.21.1': 48, '1.21': 48,
    '1.20.6': 41, '1.20.5': 41,
    '1.20.4': 26, '1.20.3': 26, '1.20.2': 18,
    '1.20.1': 15, '1.20': 15, '1.19.4': 12,
    ** ver('1.19', 1, 3, pf=10),
    '1.19': 10,
    '1.18.2': 9,
    '1.18.1': 8, '1.18': 8,
    '1.17.1': 7, '1.17': 7,
    ** ver('1.16', 2, 5, pf=6),
    '1.16.1': 5, '1.16': 5, '1.15.2': 5, '1.15.1': 5, '1.15': 5,
    ** ver('1.14', 1, 4, pf=4),
    '1.14': 4, '1.13.2': 4, '1.13.1': 4, '1.13': 4,
}
latest_mc_version = list(pack_formats.keys())[1]

DATA_EXT = 'dps'
FUNC_EXT = 'fps'

if __v_type__ not in ('release', 'dev'):
    raise AssertionError(f'Version type {__v_type__!r} is invalid')


def ns(resource: str, /, *, default: str = 'minecraft') -> str:
    return resource if ':' in resource else f'{default}:{resource}'


namespace_re = re.compile(r'[a-z0-9-_.]+')
func_re = re.compile(r'(?<!-)\bfunction\b(?!-)')

# After this version, folders were renamed to be singular
PLURAL_CUTOFF_PF: int = 45
# After this version pack formats are not integers (e.g. 82.0 instead of 82)
DECIMATED_PF: int = 82
# After this version, overlays were added
OVERLAY_PF: int = 15


def right_most_function(contents: str) -> int | None:
    # Use finditer to get match objects, which include the start and end positions of each match
    matches = list(func_re.finditer(contents))
    return matches[-1].end() if matches else None


def version_or_pf(s: str, default: PF | None=None) -> PF:
    prefix = s[:1]
    if prefix not in 'pv':
        prefix = None
    else:
        s = s[1:]
    res = pack_formats.get(s)
    if res is not None and prefix != 'p':
        return res
    try:
        dot = s.index('.')
        pf = int(s[:dot]), int(s[dot:])
        if major_pf(pf) < DECIMATED_PF or prefix == 'v': raise ValueError("Unknown pack format/version", s)
        return pf
    except ValueError:
        try:
            pf = int(s)
            if prefix == 'v': raise ValueError("Unknown pack format/version", s)
            return pf if pf < DECIMATED_PF else with_minor(pf)
        except ValueError as e:
            if default is not None:
                return default
            print(f"Tried {s!r}", file=sys.stderr)
            raise e


def major_pf(pack_format: PF) -> int:
    match pack_format:
        case (int(major), int()): pass
        case int(major): pass
        case _:
            raise ValueError(f"Invalid pack format: {pack_format!r}")
    return major

@overload
def with_minor(pack_format: object) -> Never: ...
@overload
def with_minor(pack_format: PF) -> tuple[int, int]: ...

def with_minor(pack_format: PF) -> tuple[int, int]:
    match pack_format:
        case int(major):
            return major, 0
        case [int(major), int(minor)]:
            return major, minor
        case _:
            raise ValueError(f"Invalid pack format: {pack_format!r}")

def build_globals(func_stack: list, capturer_stack: list, func_files: dict,
                  other: dict, namespace='minecraft', function_tags=None) -> dict:
    def __other__(s: str) -> dict:
        return other.setdefault(s, {})

    def __line__(ln: str) -> None:
        if capturer_stack:
            capturer_stack[-1].append(ln)
        else:
            func_files[func_stack[-1]].append(ln)

    func_def_re = re.compile(r'^([a-z\d:/_-]*)[ \t]*(?:\[([a-z\d:/_, -]*)](.*))?$')

    def __function_name__(func_def: str) -> tuple[str, str]:
        func_def_match = func_def_re.fullmatch(func_def)
        if not func_def_match:
            raise ValueError(f'Invalid function definition: {func_def!r}')
        func_name, tags, extra = func_def_match.groups()
        if func_name == '':
            func_name = f'{namespace}:anon/function'
            if func_name in func_files:
                x = 1
                while f'{func_name}_{x}' in func_files:
                    x += 1
                func_name = f'{func_name}_{x}'
        func_name = ns(func_name, default=namespace)
        if func_name in func_files:
            raise ValueError(f'Duplicate function name: {func_name!r}')
        if tags and function_tags is not None:
            for tag in tags.split(','):
                tag = ns(tag.strip())
                function_tags.setdefault(tag, []).append(func_name)
        func_files[func_name] = []
        return func_name, (extra or '')

    @contextmanager
    def __function__(func_name: str):
        func_stack.append(func_name)
        yield
        func_stack.pop()

    def __replace_function__(func_name: str):
        func_stack[-1] = func_name

    @contextmanager
    def capture_lines():
        capturer_stack.append(result := [])
        try:
            yield result
        finally:
            capturer_stack.pop()

    def n(s: str) -> str:
        return ns(s.removesuffix('.json'), default=namespace)

    class Dp:
        def __init__(self, type: tuple[str, ...]=()):
            self._type = type
        def __getattr__(self, attr: str):
            if '/'.join(self._type) in other:
                return other['/'.join(self._type)][n(attr)]
            return Dp((*self._type, attr))
        def __setattr__(self, attr: str, value: dict | list | str | bytes):
            if attr == '_type':
                object.__setattr__(self, attr, value)
                return
            other.setdefault('/'.join(self._type), {})[n(attr)] = value
        def __delattr__(self, item):
            other['/'.join(self._type)].pop(n(item))
        def __getitem__(self, item: tuple[str, str] | str):
            if self._type:
                item: str
                return other['/'.join(self._type)][n(item)]
            type, resource = item
            return other[type][n(resource)]
        def __setitem__(self, item: tuple[str, str] | str, value: dict | list | str | bytes):
            if self._type:
                item: str
                other.setdefault('/'.join(self._type), {})[n(item)] = value
                return
            type, resource = item
            other.setdefault(type, {})[n(resource)] = value
        def __delitem__(self, key):
            other['/'.join(self._type)].pop(n(key))

    dp = Dp()
    funcs = [__other__, __line__, __function_name__, __function__, __replace_function__, capture_lines]
    return {func.__name__: func for func in funcs} | {'ns': namespace, 'dp': dp}


def get_header() -> str:
    return f'# Generated by PackScript {__version__}-{__v_type__} by {__author__}{modified_by and f" modified by: {modified_by}"}\n'


def get_folder(path: str, pf: PF) -> str:
    return path if major_pf(pf) >= PLURAL_CUTOFF_PF else path + 's'


def read_pack_meta(input: Path) -> dict:
    if not (input / 'pack.mcmeta').is_file():
        raise FileNotFoundError('No pack.mcmeta found')
    try:
        pack_meta: dict | None = json.loads((input / 'pack.mcmeta').read_text())
    except ValueError:
        pack_meta = None
    if not pack_meta or not isinstance(pack_meta.get('pack'), dict):
        raise ValueError('Invalid pack.mcmeta file')
    return pack_meta


def comp_file(output_folder: Path, parent: Path, filename: Path, globals: dict[str, object], verbose=False):
    command_re = re.compile(r'([\t ]*)/(.*)')
    interpolation_re = re.compile(r'\$\{\{(.*?)}}|(?<!^)\$([a-zA-Z_]\w*)')
    code = []
    concat_line = None
    curr_file = parent / filename
    print(filename.relative_to(output_folder))
    for line in curr_file.read_text().splitlines():
        line = line.rstrip()
        if concat_line is not None:
            line = f'{concat_line}{line.lstrip()}'
            concat_line = None
        if line.endswith('\\'):
            concat_line = line[:-1]
            continue

        command_match = command_re.match(line)
        if command_match:
            indent, contents = command_match.groups()
            # replace { and } with other sequences, so they don't interfere with f string
            contents = contents.replace('{', '{{').replace('}', '}}')
            # replace interpolation with value \1\2 is a hack lmao
            # It's basically grabbing from either the first or second group, since they're mutually exclusive
            contents = interpolation_re.sub(r'{\1\2}', contents)
            extra_line = None
            if (end_chr := contents[-1:]) in (':', ';'):
                func_def_start = right_most_function(contents)
                # print('func: ', line)
                if func_def_start is None:
                    raise ValueError(f'Command {contents!r} ends with colon/semicolon but does not contain function')
                func_def = contents[func_def_start:-1].strip()
                code.append(f'{indent}__f, __extra = __function_name__(f"{func_def}")')
                contents = f'{contents[:func_def_start]} {{__f}}{{__extra}}'
                extra_line = f'{indent}with __function__(__f):'
                if end_chr == ';':
                    extra_line = f'{indent}__replace_function__(__f)'
            code.append(f'{indent}__line__(rf""" {contents} """[1:-1])')
            if extra_line:
                code.append(extra_line)
        else:
            code.append(line)
    pyth = '\n'.join(code)

    def print_code(file=sys.stdout):
        max_len = len(str(len(code)))
        for i, ln in enumerate(code, start=1):
            print(f'{i:>{max_len}}: {ln}', file=file)

    if verbose:
        print_code()
    old_path = sys.path[:]
    sys.path.insert(0, str(curr_file.parent))
    try:
        exec(pyth, globals)
    except Exception as e:
        print('Error in:', filename, file=sys.stderr)
        print_code(sys.stderr)
        raise e
    finally:
        sys.path = old_path


def comp_pack(output_folder: Path, min_pack_format: PF, max_pack_format: PF, source: bool, verbose: bool, overlay=False):
    function_tags: dict[str, list[str]] = {}
    other: dict[str, dict[str, object]] = {}
    for namespace in sorted((output_folder / 'data').iterdir()):
        namespace: Path
        func_files: dict[str, list[str]] = {'': []}
        func_stack: list[str] = ['']
        capturer_stack: list[str] = []

        globals = build_globals(func_stack, capturer_stack, func_files, other, namespace.name, function_tags)
        working_folder = (namespace / get_folder("source", max_pack_format))
        if (not get_folder('source', max_pack_format).endswith('s') and
                (namespace / 'sources').exists()):
            raise ValueError('Legacy "sources" folder detected! Rename your folders to be singular!')

        for filename in sorted(working_folder.rglob(f'*.{DATA_EXT}')):
            base = output_folder.parent if overlay else output_folder
            comp_file(base, working_folder, filename, globals, verbose=verbose)

        if not source:
            shutil.rmtree(namespace / get_folder('source', max_pack_format), ignore_errors=True)
        func_files.pop('')
        # Iterate through generated functions
        for name, content in func_files.items():
            func_dir = get_folder('function', max_pack_format)
            mcfunction_path = output_folder / 'data' / f'{name.replace(":", f"/{func_dir}/")}.mcfunction'
            if not content:
                continue
            mcfunction_path.parent.mkdir(parents=True, exist_ok=True)
            mcfunction_path.write_text(get_header() + '\n'.join(content) + '\n')

        other.setdefault(f'tags/{get_folder("function", max_pack_format)}', {}).update(
            {tag: {'values': func_names} for tag, func_names in function_tags.items()})

        # Write stuff in other
        for file_type, stuff in other.items():
            for name, content in stuff.items():
                name = name.replace(':', f'/{file_type}/')
                if '.' not in name:
                    name += '.json'
                other_path = output_folder / 'data' / name
                other_path.parent.mkdir(parents=True, exist_ok=True)
                match content:
                    case dict() | list():
                        other_path.write_text(json.dumps(content, indent=2, ensure_ascii=False, sort_keys=True))
                    case str():
                        other_path.write_text(content)
                    case bytes():
                        other_path.write_bytes(content)
                    case _:
                        raise ValueError(f'Error: invalid content: {content!r}')
    # Backport old folders if present
    if major_pf(min_pack_format) < PLURAL_CUTOFF_PF <= major_pf(max_pack_format):
        changed = [
            'structure', 'advancement', 'recipe', 'loot_table', 'predicate', 'item_modifier', 'function',
            'tags/function', 'tags/item', 'tags/block', 'tags/entity_type', 'tags/fluid', 'tags/game_event',
        ]
        for namespace in sorted((output_folder / 'data').iterdir()):
            for registry in changed:
                try:
                    shutil.copytree(namespace / registry, namespace / f'{registry}s')
                except (FileExistsError, FileNotFoundError):
                    pass


def compile(*, input: str, output: str, verbose: bool, source: bool, **_):
    input_path: Path = Path(input or '.').absolute()
    has_datapack = (input_path / 'data').is_dir()

    is_jar = output.endswith('.jar')
    is_zip = output.endswith('.zip')
    final_output_folder = Path(output.removesuffix('.zip').removesuffix('.jar')).absolute()
    if not final_output_folder.stem:
        raise ValueError('Please provide an output with a filename')
    if input_path == final_output_folder:
        raise shutil.SameFileError('Input and output directories must not have the same')

    # Create a temporary directory for building
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_output = Path(temp_dir) / final_output_folder.name
        temp_output.mkdir(parents=True, exist_ok=True)

        if has_datapack:
            data = input_path / 'data'
            if not data.exists() or not (input_path / 'pack.mcmeta').exists():
                raise FileNotFoundError('Need data folder and pack.mcmeta')
            if is_jar and not any((input_path / m).exists() for m in ('fabric.mod.json', 'mods.toml', 'neoforge.mods.toml')):
                raise FileNotFoundError(f'Need "fabric.mod.json" and/or "mods.toml" and/or '
                                        f'"neoforge.mods.toml" Use {sys.argv[0]} init --modded')

            def config(loc: str, *, dst='', mkdirs=False, dirs_exist_ok=False) -> bool:
                type = 'dir' if loc.endswith('/') else 'file'
                src = input_path / loc
                dst = temp_output / (dst or loc)
                if not (src.is_file() if type == 'file' else src.is_dir()):
                    if src.exists():
                        raise (IsADirectoryError if type == 'file' else NotADirectoryError)(loc)
                    return False
                if mkdirs:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                if type == 'file':
                    shutil.copy(src, dst)
                else: # type == 'dir'
                    shutil.copytree(src, dst, dirs_exist_ok=dirs_exist_ok, ignore=shutil.ignore_patterns(".DS_Store"))
                return True

            has_overlays = config('overlays/', dst='./', dirs_exist_ok=True)
            config('data/')
            config('pack.png')
            if is_jar:
                config('assets/')
                config('fabric.mod.json')
                config('mods.toml', dst='META-INF/mods.toml', mkdirs=True)
                config('mods.toml', dst='META-INF/neoforge.mods.toml')
                config('neoforge.mods.toml', dst='META-INF/neoforge.mods.toml', mkdirs=True)
            pack_meta = read_pack_meta(input_path)
            target_pack_format = pack_meta.get('pack', {}).get('pack_format')
            min_pack_format = with_minor(pack_meta.get('pack', {}).get('min_format', target_pack_format))
            max_pack_format = with_minor(pack_meta.get('pack', {}).get('max_format', target_pack_format))

            comp_pack(temp_output, min_pack_format, max_pack_format, source, verbose)
            if has_overlays:
                registered_overlays = pack_meta.setdefault('overlays', {}).setdefault('entries', [])
                registered_overlay_names = set(reg['directory'] for reg in registered_overlays)
                overlay_re = re.compile(r'([pv]?[\d.]+)-([pv]?[\d.]+|future)')
                renames = []
                for overlay in sorted((input_path / 'overlays').iterdir()):
                    overlay_dst_name = overlay.name.replace('.', '_')
                    if overlay_dst_name != overlay.name:
                        renames.append((overlay.name, overlay_dst_name))
                    if overlay_dst_name in registered_overlay_names:
                        continue
                    elif overlay_match := overlay_re.fullmatch(overlay.name.replace('_', '.')):
                        min_pf, max_pf = map(version_or_pf, overlay_match.groups())
                    elif pf := version_or_pf(overlay.name.replace('_', '.'), default=False):
                        min_pf = max_pf = pf
                    else:
                        raise ValueError(f'Unregistered overlay {overlay_dst_name!r}, add it to pack.mcmeta or name it '
                                         f'after the version(s) it is for (v1.20.2, v1.20.3-v1.20.5)')
                    overlay_value = {
                        'formats': [major_pf(min_pf), major_pf(max_pf)],
                        'min_format': with_minor(min_pf), 'max_format': with_minor(max_pf),
                        'directory': overlay_dst_name,
                    }

                    if with_minor(min_pack_format) >= (DECIMATED_PF, 0):
                        del overlay_value['formats']
                    registered_overlays.insert(0, overlay_value)
                for src_overlay, dst_overlay in renames:
                    shutil.move(temp_output / src_overlay, temp_output / dst_overlay)
                for overlay in registered_overlays:
                    path = temp_output / overlay['directory']
                    comp_pack(path, min_pf, max_pf, source, verbose, overlay=True)
            (temp_output / 'pack.mcmeta').write_text(json.dumps(pack_meta, indent=4))

        func_files = {}
        for f in sorted(input_path.glob(f'*.{FUNC_EXT}')):
            func_stack = [f.name]
            func_files[f.name] = []
            globals = build_globals(func_stack, [], func_files, {})

            comp_file(input_path, input_path, f, globals, verbose=verbose)
        if func_files:
            temp_output.mkdir(parents=True, exist_ok=True)
        for f, content in func_files.items():
            f = f[f.find(':') + 1:].replace('/', '_').removesuffix(f'.{FUNC_EXT}')
            mcfunction_path = temp_output / f'{f}.mcfunction'
            mcfunction_path.write_text(get_header() + '\n'.join(content) + '\n')
        if not func_files and not has_datapack:
            print("No datapack/func_files found!")
            return

        if is_zip or is_jar:
            cwd = Path.cwd()
            try:
                os.chdir(temp_dir)
                shutil.make_archive(temp_output.name, 'zip', temp_output.name)
                if is_jar:
                    zip_path = Path(temp_dir) / f"{temp_output.name}.zip"
                    jar_path = final_output_folder.parent / f"{final_output_folder.name}.jar"
                    shutil.copy(zip_path, jar_path)
                else:
                    zip_path = Path(temp_dir) / f"{temp_output.name}.zip"
                    final_zip_path = final_output_folder.parent / f"{final_output_folder.name}.zip"
                    shutil.copy(zip_path, final_zip_path)
            finally:
                os.chdir(cwd)
        else:
            if final_output_folder.exists():
                for item in final_output_folder.iterdir():
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                    else:
                        shutil.rmtree(item)
            else:
                final_output_folder.mkdir(parents=True, exist_ok=True)

            for item in temp_output.iterdir():
                if item.is_file():
                    shutil.copy2(item, final_output_folder / item.name)
                else:
                    shutil.copytree(item, final_output_folder / item.name, dirs_exist_ok=True)


def init_modded_template(name: str, description: str, output: Path, namespace: str) -> None:
    (output / 'fabric.mod.json').write_text(json.dumps({
        "schemaVersion": 1,
        "id": namespace,
        "version": "1.0",
        "name": name,
        "description": description,
        "authors": [],
        "depends": {
            "minecraft": "*",
            "fabric-api": "*",
        },
        "icon": "pack.png",
    }, indent=4, sort_keys=True))
    (output / 'mods.toml').write_text(textwrap.dedent(f'''
        # By default 'mods.toml' will be copied to 'neoforge.mods.toml' as well,
        # Create a separate 'neoforge.mods.toml' to override values here
        modLoader="lowcodefml"
        loaderVersion="[1,)"
        license="All Rights Reserved"
        showAsResourcePack=false
        showAsDataPack=false

        [[mods]]
        modId="{namespace}"
        version="1.0"
        description="""{description}"""
        logoFile="pack.png"
        authors=""
    '''.lstrip('\n')))


def init_template(*, name: str, description: str, pack_format: PF, output: str, modded: bool | None, namespace: str, **_) -> None:
    if modded and (Path(output or '.') / 'pack.mcmeta').is_file():
        path = Path(output or '.')
        meta = read_pack_meta(path)
        description: str | None = description or meta.get('pack', {}).get('description')
        if description is None:
            description: str = input('Description ():')
        namespaces = [d.name for d in (path / 'data').iterdir() if d.is_dir() and d.name != 'minecraft']
        default_ns = namespaces and namespaces[0]
        namespace = namespace or input(f'Namespace ({default_ns}): ') or str(default_ns)
        def_name = path.parent.resolve().name
        name = name or input(f'Name ({def_name}):') or def_name
        init_modded_template(name, description, path, namespace)
        return
    if not all((name, description, pack_format, output, namespace)):
        print('Leave a field empty to have it set to its default value')
    name = name or input('Datapack Name (Datapack): ') or 'Datapack'
    def_ns = re.sub(r'\W', '-', name.lower().replace(' ', '_'))
    namespace = namespace or input(f'Namespace ({def_ns}): ') or def_ns
    namespace = re.sub(r'\W', '-', namespace.lower().replace(' ', '_'))
    if not namespace_re.fullmatch(namespace):
        raise ValueError(f'Namespace must match regex: /{namespace_re.pattern}/ ({namespace} does not match)')
    v = ''
    while not pack_format:
        v = input(f'Pack Format/Minecraft Version ({latest_mc_version}): ') or latest_mc_version
        try:
            pack_format = version_or_pf(v)
        except ValueError:
            print(f"You must provide a recognized mc version or a pack format, {v!r} is neither.")
    v = v and f' for version {v}'
    description = description or input(f'Description (Datapack {name!r}{v}): ') or \
                  f'Datapack {name!r}{v}'
    modded = modded if modded is not None else input('Add modded metadata for '
                                                     'forge/fabric/neoforge? y/n (n): ')[:1].lower() == 'y'
    output: str = output or input(f'Output Directory ({name.replace(" ", "_")}): ') or name.replace(' ', '_')
    output: Path = Path(output).absolute()
    if (output / 'data').exists() or (output / 'pack.mcmeta').exists():
        raise ValueError('data or pack.mcmeta already present in this directory, '
                         'remove them to generate the template, or specify a different directory.')
    source = (output / 'data' / namespace / get_folder("source", pf=pack_format))
    source.mkdir(parents=True, exist_ok=True)
    (source / f'main.{DATA_EXT}').write_text(textwrap.dedent(f'''
        /function tick [tick]:
            /seed
        /function load [load]:
            /tellraw @a "Loaded {name}"
    '''.lstrip('\n')))
    major = major_pf(pack_format)
    pack_meta = {
        'pack': {
            'pack_format': major,
            'min_format': pack_format, 'max_format': pack_format,
            'supported_formats': [major, major],
            'description': description,
        }
    }
    if major >= DECIMATED_PF:
        del pack_meta['pack']['supported_formats']
    (output / 'pack.mcmeta').write_text(json.dumps(pack_meta, indent=4, sort_keys=True))
    if modded:
        init_modded_template(name, description, output, namespace)


# <editor-fold defaultstate="collapsed" desc="def update_pack_format(): ...">
def update_pack_format(*, input: str, target: str, min_pf: str, max_pf: str, **_) -> None:
    input: Path = Path(input or '.').absolute()
    pack_meta = read_pack_meta(input)
    pack_data = pack_meta.setdefault('pack', {})
    target_pack_format = pack_data.get('pack_format')
    if not isinstance(target_pack_format, int):
        raise ValueError('Invalid pack.mcmeta file')
    target_pack_format: int
    min_pack_format, max_pack_format = None, None
    match pack_data.get('supported_formats'):
        case [min_pack_format, max_pack_format]: pass
        case {'min_inclusive': min_pack_format, 'max_inclusive': max_pack_format}: pass

    min_pack_format = pack_data.get('min_format', min_pack_format)
    max_pack_format = pack_data.get('max_format', max_pack_format)

    if target or min_pf or max_pf:
        target: PF = major_pf(version_or_pf(target, target_pack_format))
        min_pf: PF = min(with_minor(version_or_pf(min_pf, min_pack_format)) or target, with_minor(target))
        max_pf: PF = max(with_minor(version_or_pf(max_pf, max_pack_format)) or target, with_minor(target))
        pack_data['min_format'] = min_pf
        pack_data['max_format'] = max_pf
        pack_data['supported_formats'] = [major_pf(min_pf), major_pf(max_pf)]
        if major_pf(min_pf) >= DECIMATED_PF:
            del pack_data['supported_formats']
        pack_data['pack_format'] = target
        (input / 'pack.mcmeta').write_text(json.dumps(pack_meta, indent=4, sort_keys=True))
    else:
        min_pack_format: PF; max_pack_format: PF
        target: PF; min_pf: PF; max_pf: PF
        target, min_pf, max_pf = target_pack_format, min_pack_format, max_pack_format
        print('edit these values via the --min, --target, or --max options')

    def versions_of(pf: PF) -> str:
        # be strict if pf is strict, otherwise be loose
        func = major_pf if isinstance(pf, int) else with_minor
        return f"({', '.join(key for key, value in pack_formats.items() if func(value) == func(pf))})"

    isatty = sys.stdout.isatty()
    def c(s: str) -> str:
        """ color numbers in a string with ansi codes """
        return re.sub(r'(\d+)', '\033[33m\\1\033[0m', s) if isatty else s

    if max_pf:
        print(c(f"{'max pack_format:':<20}{max_pf!s:>9} {versions_of(max_pf)}"))
    print(c(f"{'target pack_format:':<20}{target!s:>9} {versions_of(target)}"))
    if min_pf:
        print(c(f"{'min pack_format:':<20}{min_pf!s:>9} {versions_of(min_pf)}"))
# </editor-fold>


def main(*argv):
    parser = argparse.ArgumentParser(
        description='This is a datapack compiler for Minecraft\n'
                    'Source: https://github.com/Slackow/packscript',
        formatter_class=argparse.RawTextHelpFormatter,
        usage='packscript [-V | --version] [-h | --help] <command> [<args>]')
    parser.add_argument('-V', '--version', help='Print out the version', default=False, action='store_true')
    subparsers = parser.add_subparsers(dest='command', title='Commands', metavar='')

    # "compile" command
    parser_compile = subparsers.add_parser('compile', aliases=['comp', 'c'],
                                           help='Compile the datapack. Accepts arguments.\n'
                                                '"packscript comp --help" for more info',
                                           description='Compile the datapack\n\n'
                                                       'Use this command to compile your datapack into a format that '
                                                       'Minecraft can read.',
                                           formatter_class=argparse.RawTextHelpFormatter)
    parser_compile.add_argument('-o', '--output', type=str, help='Output directory/zip', default='output')
    parser_compile.add_argument('-i', '--input', type=str, help='Input directory', default='.')
    parser_compile.add_argument('-v', '--verbose', help='Print generated Python code.', default=False,
                                action='store_true')
    parser_compile.add_argument('-S', '--source', help='Include source files in output.', default=False,
                                action='store_true')

    # "init" command
    parser_init = subparsers.add_parser('init',
                                        help='Initialize datapack template (interactively). Accepts arguments.\n'
                                             '"packscript init --help" for more info',
                                        description='Initialize a new datapack template\n\n'
                                                    'Use this command to create a new datapack template, setting '
                                                    'up a basic structure for your project. '
                                                    'Information can be provided in args or interactively.',
                                        formatter_class=argparse.RawTextHelpFormatter)
    parser_init.add_argument('-o', '--output', type=str, help='Output directory', default='')
    parser_init.add_argument('-N', '--name', type=str, help='Name of the datapack', default='')
    parser_init.add_argument('-n', '--namespace', type=str, help='Custom namespace name', default='')
    parser_init.add_argument('-d', '--description', type=str, help='The description of the datapack', default='')
    parser_init.add_argument('-f', '--pack-format', type=int,
                             help='Pack format (keeps track of compatible versions)', default=0)
    parser_init.add_argument('-m', '--modded', help='Init modded config files, for fabric, forge, and neoforge',
                             action='store_true', default=None)
    parser_init.add_argument('--no-modded', action='store_false', dest='modded', help='Do not initialize any modded config files')

    # "pack_format" command
    parser_pack_format = subparsers.add_parser('pack_format', aliases=['pf'],
                                               help='Read and update pack_formats and see their associated versions, '
                                                    'pack format numbers/versions strings are interchangeable, '
                                                    'and min/max must be within the range of target',
                                               description="Update or view your pack's supported pack format versions.",
                                               formatter_class=argparse.RawTextHelpFormatter)
    parser_pack_format.add_argument('-i', '--input', type=str, help='Input directory', default='.')
    parser_pack_format.add_argument('-t', '--target', type=str, help='Set the target pack_format', default='')
    parser_pack_format.add_argument('-m', '--min', type=str, help='Set the minimum pack_format', default='')
    parser_pack_format.add_argument('-M', '--max', type=str, help='Set the maximum pack_format', default='')

    args = parser.parse_args(argv)

    args_dict = vars(args)
    if args.version:
        print(f'PackScript {__version__}-{__v_type__}')
    elif args.command is None:
        parser.print_help()
    elif args.command.startswith('c'):
        compile(**args_dict)
    elif args.command.startswith('p'):
        update_pack_format(min_pf=args.min, max_pf=args.max, **args_dict)
    else:
        try:
            init_template(**args_dict)
        except KeyboardInterrupt:
            print('\nInterrupted')
            sys.exit(130)


if __name__ == '__main__':
    main(*sys.argv[1:])