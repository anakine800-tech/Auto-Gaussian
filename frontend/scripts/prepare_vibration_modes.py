"""Build one local display sidecar offline; never modify the source or store."""
import argparse
import json
from pathlib import Path
from autog_frontend.vibrations import build_modes

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--details',type=Path,required=True)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    packet=build_modes(json.loads(args.details.read_text()),args.log.read_bytes())
    with args.output.open('x') as stream:
        json.dump(packet,stream,ensure_ascii=True,allow_nan=False,sort_keys=True,indent=2)
        stream.write('\n')
    print('Prepared',len(packet['modes']),'source-bound modes; no scientific acceptance')
