from __future__ import print_function
import os
import argparse
import torch
import torch.backends.cudnn as cudnn
import numpy as np
from data import cfg
from layers.functions.prior_box import PriorBox
from utils.nms_wrapper import nms
#from utils.nms.py_cpu_nms import py_cpu_nms
import cv2
from models.faceboxes import FaceBoxes
from utils.box_utils import decode
from utils.timer import Timer
import time

parser = argparse.ArgumentParser(description='FaceBoxes')

parser.add_argument('-m', '--trained_model', default='weights/FaceBoxes.pth',
                    type=str, help='Trained state_dict file path to open')
parser.add_argument('--save_result', default=False, type=bool, help='Determine to save the result of not')
parser.add_argument('--save_folder', default='eval/', type=str, help='Dir to save results')
parser.add_argument('--cpu', action="store_true", default=False, help='Use cpu inference')
parser.add_argument('--resize', default=1, type=float, help='resize')
parser.add_argument('--confidence_threshold', default=0.05, type=float, help='confidence_threshold')
parser.add_argument('--facebox_threshold', default=0.9, type=float, help='facebox_threshold')
parser.add_argument('--top_k', default=5000, type=int, help='top_k')
parser.add_argument('--nms_threshold', default=0.3, type=float, help='nms_threshold')
parser.add_argument('--keep_top_k', default=750, type=int, help='keep_top_k')
args = parser.parse_args()


def check_keys(model, pretrained_state_dict):
    ckpt_keys = set(pretrained_state_dict.keys())
    model_keys = set(model.state_dict().keys())
    used_pretrained_keys = model_keys & ckpt_keys
    unused_pretrained_keys = ckpt_keys - model_keys
    missing_keys = model_keys - ckpt_keys
    print('Missing keys:{}'.format(len(missing_keys)))
    print('Unused checkpoint keys:{}'.format(len(unused_pretrained_keys)))
    print('Used keys:{}'.format(len(used_pretrained_keys)))
    assert len(used_pretrained_keys) > 0, 'load NONE from pretrained checkpoint'
    return True


def remove_prefix(state_dict, prefix):
    ''' Old style model is stored with all names of parameters sharing common prefix 'module.' '''
    print('remove prefix \'{}\''.format(prefix))
    f = lambda x: x.split(prefix, 1)[-1] if x.startswith(prefix) else x
    return {f(key): value for key, value in state_dict.items()}


def load_model(model, pretrained_path, load_to_cpu):
    print('Loading pretrained model from {}'.format(pretrained_path))
    if load_to_cpu:
        pretrained_dict = torch.load(pretrained_path, map_location=lambda storage, loc: storage)
    else:
        device = torch.cuda.current_device()
        pretrained_dict = torch.load(pretrained_path, map_location=lambda storage, loc: storage.cuda(device))
    if "state_dict" in pretrained_dict.keys():
        pretrained_dict = remove_prefix(pretrained_dict['state_dict'], 'module.')
    else:
        pretrained_dict = remove_prefix(pretrained_dict, 'module.')
    check_keys(model, pretrained_dict)
    model.load_state_dict(pretrained_dict, strict=False)
    return model


if __name__ == '__main__':
    torch.set_grad_enabled(False)
    # net and model
    net = FaceBoxes(phase='test', size=None, num_classes=2)    # initialize detector
    net = load_model(net, args.trained_model, args.cpu)
    net.eval()
    print('Finished loading model!')
    print(net)
    cudnn.benchmark = True
    device = torch.device("cpu" if args.cpu else "cuda")
    net = net.to(device)

    # save result or not
    if args.save_result:
        # save file
        if not os.path.exists(args.save_folder):
            os.makedirs(args.save_folder)

    # testing scale
    resize = args.resize

    _t = {'forward_pass': Timer(), 'misc': Timer()}

    first_img = True

    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("ERROR: NO VIDEO STREAM OR NO CAMERA DEVICE.")

    else:
        # set camera's width and height
        cap.set(3, 1280) # width
        cap.set(4, 720)  # height

        # testing begin - camera
        i = 0
        while True:

            hasFrame, frame = cap.read()

            if hasFrame:

                img = np.float32(frame)

                if first_img:
                    print(img.shape)

                if resize != 1:
                    img = cv2.resize(img, None, None, fx=resize, fy=resize, interpolation=cv2.INTER_LINEAR)
                    
                im_height, im_width, _ = img.shape

                if first_img:
                    print(img.shape)
                    first_img = False

                scale = torch.Tensor([img.shape[1], img.shape[0], img.shape[1], img.shape[0]])
                img -= (104, 117, 123)
                img = img.transpose(2, 0, 1)
                img = torch.from_numpy(img).unsqueeze(0)
                img = img.to(device)
                scale = scale.to(device)

                _t['forward_pass'].tic()
                # start = time.time()
                out = net(img)  # forward pass
                # end = time.time()
                _t['forward_pass'].toc()
                _t['misc'].tic()

                priorbox = PriorBox(cfg, out[2], (im_height, im_width), phase='test')
                priors = priorbox.forward()
                priors = priors.to(device)
                loc, conf, _ = out
                prior_data = priors.data
                boxes = decode(loc.data.squeeze(0), prior_data, cfg['variance'])
                boxes = boxes * scale / resize
                boxes = boxes.cpu().numpy()
                scores = conf.data.cpu().numpy()[:, 1]

                # ignore low scores
                inds = np.where(scores > args.confidence_threshold)[0]
                boxes = boxes[inds]
                scores = scores[inds]

                # keep top-K before NMS
                order = scores.argsort()[::-1][:args.top_k]
                boxes = boxes[order]
                scores = scores[order]

                # do NMS
                dets = np.hstack((boxes, scores[:, np.newaxis])).astype(np.float32, copy=False)
                #keep = py_cpu_nms(dets, args.nms_threshold)
                keep = nms(dets, args.nms_threshold,force_cpu=args.cpu)
                dets = dets[keep, :]

                # keep top-K faster NMS
                dets = dets[:args.keep_top_k, :]
                _t['misc'].toc()

                xmax = 0.0
                xmin = 0.0
                ymax = 0.0
                ymin = 0.0

                # save dets
                for k in range(dets.shape[0]):
                    xmin = dets[k, 0]
                    ymin = dets[k, 1]
                    xmax = dets[k, 2]
                    ymax = dets[k, 3]
                    ymin += 0.2 * (ymax - ymin + 1)
                    score = dets[k, 4]

                    if score >= args.facebox_threshold:
                        cv2.rectangle(frame, (int(xmin), int(ymin)), (int(xmax), int(ymax)), (255, 0, 0), 2)

                print('im_detect: {:d} forward_pass_time: {:.4f}s misc: {:.4f}s '.format(i + 1, _t['forward_pass'].average_time, _t['misc'].average_time))
                cv2.imshow("Faceboxes-Pytorch", frame)

                # save result or not
                if args.save_result:
                    cv2.imwrite(args.save_folder + "/" + str(i+1) + ".jpg", frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    cv2.destroyAllWindows()
                    break

                i += 1
