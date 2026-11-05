"""Assembler checks for frozen loader slots and restored constant targets."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loadgame_compile as adapter

ARM = 'C:/devkitPro/devkitARM/bin/arm-none-eabi-'
ROOT = Path(__file__).resolve().parents[2]


def rejected(action):
    try:
        action()
    except AssertionError:
        return
    raise AssertionError('Invalid assembly accepted')


def main():
    out = ROOT/'scratch/loadgame-slot-test'
    out.mkdir(exist_ok=True)
    source = '.syntax unified\n.arm\n.section .text.test,"ax",%progbits\n'
    for name in ('CtrBootlog_hide', 'CtrScreens_moveConsoles'):
        source += f'.global {name}\n.type {name},%function\n{name}:\n bx lr\n.size {name}, .-{name}\n'
    for game, model, size in (('undertale','o3ds',496), ('undertale','n3ds',592),
                             ('deltarune','o3ds',592), ('deltarune','n3ds',592)):
        path, obj, raw = out/'slots.s', out/'slots.o', out/'slots.bin'
        path.write_text(adapter.main_slots(source,game,model),encoding='utf-8')
        subprocess.run([ARM+'as.exe','--fatal-warnings',str(path),'-o',str(obj)],
                       check=True,stdin=subprocess.DEVNULL,timeout=10)
        subprocess.run([ARM+'objcopy.exe','-O','binary',str(obj),str(raw)],
                       check=True,stdin=subprocess.DEVNULL,timeout=10)
        expected = bytes.fromhex('1eff2fe1')+bytes(244)
        expected += bytes.fromhex('1eff2fe1')+bytes(size-252)
        assert raw.read_bytes() == expected, (game,model)
    rejected(lambda: adapter.main_slots(source.replace('CtrBootlog_hide, .-CtrBootlog_hide',
                                                       'other, .-other'),'undertale','o3ds'))
    rejected(lambda: adapter.main_slots(source+source,'undertale','o3ds'))
    path.write_text(adapter.main_slots(source.replace(' bx lr',' .space 252',1),
                                       'undertale','o3ds'),encoding='utf-8')
    bad = subprocess.run([ARM+'as.exe','--fatal-warnings',str(path),'-o',str(obj)],
                         capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=10)
    assert bad.returncode and 'backwards' in bad.stderr
    constants = '.section .rodata.test,"a",%progbits\n.align 1\n.set .LANCHOR0, . + 0\n'
    constants += '.type second, %object\n.size second, 4\nsecond:\n.ascii "bbb\\000"\n'
    constants += '.type first, %object\n.size first, 2\nfirst:\n.ascii "a\\000"\n'
    constants += '.section .text\n.word .LANCHOR0+4\n.word .LANCHOR0+1\n'
    sections = {'.rodata.test': [dict(name='first',size=2,offset=0),
                                dict(name='second',size=4,offset=2)]}
    restored = adapter.constants(constants,sections)
    assert restored.index('first:') < restored.index('second:')
    assert '.word first\n.word second+1' in restored and '.LANCHOR' not in restored
    rejected(lambda: adapter.constants(constants.replace('.word .LANCHOR0+4',
                                                          'ldr r0, .LANCHOR0+4'),sections))
    rejected(lambda: adapter.constants(constants.replace('.size first, 2','.size first, 3'),sections))
    rejected(lambda: adapter.constants(constants.replace('second:', 'unknown:'),sections))
    # A whole helper may fill a retained cold slot only after its returning
    # original entry; assembly must reject even a 4 B overflow.
    owners = {'lsDrawDog':['Loadgame_packFallback'],
              'lsDrawText':['Loadgame_layout','Loadgame_framebuffer'],
              'lsBegin':['Loadgame_consoleBack'], 'psSaveShot':['Loadgame_prepare','Loadgame_format','Loadgame_present','Loadgame_saveShot','Loadgame_swap']}
    source='.syntax unified\n.arm\n.section .rodata\n.byte 1,1\n';entries=[]
    for i,name in enumerate(owners):
        source += f'.section .text.test,"ax",%progbits\n.type {name},%function\n{name}:\n bx lr\n.size {name}, .-{name}\n'
        entries.append(dict(name=name,size=32 if name=='psSaveShot' else 16,offset=i*16))
    for names in owners.values():
        for name in names:
            source+=f'.section .text.late.loadgame,"ax",%progbits\n.type {name},%function\n{name}:\n bx lr\n.size {name}, .-{name}\n'
    packed=adapter.retain(source,{'.text.test':entries},True,'undertale')
    path.write_text(packed,encoding='utf-8')
    subprocess.run([ARM+'as.exe','--fatal-warnings',str(path),'-o',str(obj)],check=True,stdin=subprocess.DEVNULL,timeout=10)
    overflow=source.replace('Loadgame_packFallback:\n bx lr','Loadgame_packFallback:\n .space 16\n bx lr')
    path.write_text(adapter.retain(overflow,{'.text.test':entries},True,'undertale'),encoding='utf-8')
    bad=subprocess.run([ARM+'as.exe','--fatal-warnings',str(path),'-o',str(obj)],capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=10)
    assert bad.returncode and 'backwards' in bad.stderr
    print('PASS: four target slots, zero tails, overflow and malformed input rejection; named constant targets restored')


if __name__ == '__main__':
    main()
