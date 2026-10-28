"""Inspect the actual PE manifest without launching or elevating the program."""
from pathlib import Path
import json
import sys
import xml.etree.ElementTree as ET

import pefile


def verify(executable):
    levels=[]
    with pefile.PE(str(executable)) as pe:
        for resource in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if resource.id!=24:continue  # RT_MANIFEST
            for identity in resource.directory.entries:
                for language in identity.directory.entries:
                    entry=language.data.struct
                    if entry.Size>1024*1024:raise ValueError('Manifest resource is too large')
                    root=ET.fromstring(pe.get_data(entry.OffsetToData,entry.Size))
                    levels.extend(node.attrib for node in root.iter('{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel'))
    if len(levels)!=1 or levels[0].get('level')!='requireAdministrator' or levels[0].get('uiAccess')!='false':
        raise ValueError(f'Expected requireAdministrator / uiAccess=false; found {levels}')
    return {'status':'passed','level':'requireAdministrator','uiAccess':False,'executable':str(Path(executable))}


if __name__=='__main__':
    print(json.dumps(verify(Path(sys.argv[1])),ensure_ascii=False))
