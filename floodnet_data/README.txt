FloodNet Dataset - SegFormer Ready Layout
============================================================

Source: https://github.com/BinaLab/FloodNet-Supervised_v1.0
Original Imagery: High-resolution UAS imageries (Hurricane Harvey)
Original Resolution: 4000 x 3000
Processed Resolution: 640 x 480 (preserving 4:3 aspect ratio)
Resampling: Bilinear for images, Nearest-Neighbor for annotations

DIRECTORY LAYOUT
------------------------------------------------------------
floodnet_data/
├── raw/                         # Untouched original archives and files
│   ├── FloodNet.zip             # Downloaded zip archive (13.06 GB)
│   └── FloodNet-Supervised_v1.0/
├── processed/
│   ├── images/
│   │   ├── train/               # 1,445 RGB PNG images (640x480)
│   │   ├── val/                 # 450 RGB PNG images (640x480)
│   │   └── test/                # 448 RGB PNG images (640x480)
│   └── annotations/
│       ├── train/               # 1,445 single-channel 8-bit PNG masks
│       ├── val/                 # 450 single-channel 8-bit PNG masks
│       └── test/                # 448 single-channel 8-bit PNG masks
├── checks/                      # 6 overlay samples with colored masks
├── .venv/                       # Isolated virtual environment
└── README.txt                   # This documentation

SPLIT COUNTS
------------------------------------------------------------
Train: 1,445 images & annotations (61.7%)
Val:     450 images & annotations (19.2%)
Test:    448 images & annotations (19.1%)
Total: 2,343 images & annotations (100%)

CLASS REMAPPING TABLE
------------------------------------------------------------
Raw Class ID -> Target Class ID (Semantic Meaning)
  0 (Background)          -> 0 (Background / Other)
  1 (Building-flooded)    -> 1 (Flooded)
  2 (Building-non-flooded)-> 0 (Background / Other)
  3 (Road-flooded)        -> 1 (Flooded)
  4 (Road-non-flooded)    -> 0 (Background / Other)
  5 (Water)               -> 2 (Natural Water)
  6 (Tree)                -> 0 (Background / Other)
  7 (Vehicle)             -> 0 (Background / Other)
  8 (Pool)                -> 0 (Background / Other)
  9 (Grass)               -> 0 (Background / Other)
  Other / Invalid         -> 255 (Unlabeled / Ignore)

TRAIN SPLIT CLASS BALANCE
------------------------------------------------------------
  Class   0 (Background / Other          ):  376,188,864 px ( 84.75%)
  Class   1 (Flooded (Building + Road)   ):   19,140,725 px (  4.31%)
  Class   2 (Natural Water               ):   48,574,411 px ( 10.94%)
  Class 255 (Unlabeled / Ignore          ):            0 px (  0.00%)
