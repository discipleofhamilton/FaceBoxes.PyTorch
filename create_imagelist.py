import os
import sys

def main():

    # check numbers of command line arguments
    if len(sys.argv[1:]) == 1:

        # get command line arguments
        testset_folder = os.path.join('data', sys.argv[1], 'images/')
        testset_list = os.path.join('data', sys.argv[1], 'img_list.txt')

        # check the output file does existed or not
        # if exitsted, then delete the original one
        if os.path.exists(testset_list):
            os.remove(testset_list)
        fw = open(os.path.join(testset_list), 'w')

    for filename in os.listdir(testset_folder):
        name, subname = filename.split('.')
        # print(name, subname)
        fw.write('{} \n'.format(name))
    fw.close()

if __name__ == "__main__":
    main()