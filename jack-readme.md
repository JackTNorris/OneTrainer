#To Run:

 python .\auto-brennen.py --input_directory=<INPUT_DIRECTORY>

 As an example, the imput_directory could be : E:\B\Pozy\Downloaded_Folder\Collage. For this, for every folder in the collage folder, you are creating a model

 If you are dealing with PNGs, make sure the "sample-image-format" value in the arguments.json file is PNG. Otherwise, use JPG

 Files are "crawled" via their last edit, so feel free to go into your folder of choice and sort by date

 If you want to change the formula for calculating the number of epochs, look at lines 106-110

 If you simply want to change the "max_steps" (and hence, the number of epochs), change the "8000" figure at the top of the file for whatever value you choose

 If you want to change the scheme for backups (use a different metrics, save more / less often, e.t.c), change lines 102 - 106 in arguments.json