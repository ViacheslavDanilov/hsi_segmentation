import argparse
import multiprocessing
from functools import partial

import ffmpeg
import imutils
import pandas as pd
from tqdm import tqdm
from tqdm.contrib.concurrent import process_map

from tools.utils import *

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%d.%m.%Y %I:%M:%S',
    filename='logs/{:s}.log'.format(Path(__file__).stem),
    filemode='w',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def process_hsi(
        file_path: str,
        save_dir: str,
        data_type: str = 'absorbance',
        color_map: str = None,
        apply_equalization: bool = False,
        output_type: str = 'image',
        output_size: Tuple[int, int] = (744, 1000),
        fps: int = 15,
) -> List:

    assert output_type == 'image' or output_type == 'video', f'Incorrect output_type: {output_type}'

    # Read HSI file and extract additional information
    hsi = read_hsi(
        path=file_path,
        data_type=data_type,
    )
    body_part = extract_body_part(file_path)
    date, time = extract_time_stamp(filename=Path(file_path).name)

    # Select output_dir based on output_type
    _hsi_name = Path(file_path).stem.lower()
    hsi_name = _hsi_name.replace('_speccube', '')
    test_dir = Path(file_path).parents[2].name
    if output_type == 'image':
        output_dir = os.path.join(save_dir, test_dir, hsi_name)
    else:
        output_dir = os.path.join(save_dir, test_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Create video writer
    if output_type == 'video':
        video_path_temp = os.path.join(output_dir, f'{hsi_name}_temp.mp4')
        _img = imutils.resize(hsi[:, :, 0], height=output_size[0], inter=cv2.INTER_LINEAR)
        _img_size = _img.shape[:-1] if len(_img.shape) == 3 else _img.shape
        video_height, video_width = _img_size
        video = cv2.VideoWriter(
            video_path_temp,
            cv2.VideoWriter_fourcc(*'mp4v'),
            fps,
            (video_width, video_height),
        )

    # Process HSI in an image-by-image fashion
    metadata = []
    for idx in range(hsi.shape[2]):

        img = hsi[:, :, idx]
        img_name = f'{idx+1:03d}.png'
        img_path = os.path.join(output_dir, img_name)

        metadata.append(
            {
                'Source dir': str(Path(file_path).parent),
                'Test name': str(test_dir),
                'HSI name': str(Path(file_path).name),
                'Date': date,
                'Time': time,
                'Body part': body_part,
                'Image path': img_path,
                'Image name': img_name,
                'Min': np.min(img),
                'Mean': np.mean(img),
                'Max': np.max(img),
                'Height': img.shape[0],
                'Width': img.shape[1],
                'Wavelength': idx+1,
            }
        )

        # Resize and normalize image
        img_size = img.shape[:-1] if len(img.shape) == 3 else img.shape
        if img_size != output_size:
            img = imutils.resize(img, height=output_size[0], inter=cv2.INTER_LINEAR)
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

        # Equalize histogram
        if apply_equalization:
            img = cv2.equalizeHist(img)

        # Colorize image
        if isinstance(color_map, str) and color_map is not None:
            cmap = get_color_map(color_map)
            img = cv2.applyColorMap(img, cmap)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)

        # Save image
        if output_type == 'image':
            cv2.imwrite(img_path, img)
        elif output_type == 'video':
            video.write(img)
        else:
            raise ValueError(f'Unknown output_type value: {output_type}')

    video.release() if output_type == 'video' else False

    # Replace OpenCV videos with FFmpeg ones
    if output_type == 'video':
        video_path = os.path.join(output_dir, f'{hsi_name}.mp4')
        stream = ffmpeg.input(video_path_temp)
        stream = ffmpeg.output(stream, video_path, vcodec='libx264', video_bitrate='10M')
        ffmpeg.run(stream, quiet=True, overwrite_output=True)
        os.remove(video_path_temp)

    logger.info(f'HSI processed......: {Path(file_path).name}')

    return metadata


def main(
        input_dir: str,
        save_dir: str,
        data_type: str = 'absorbance',
        color_map: str = None,
        apply_equalization: bool = False,
        output_type: str = 'image',
        output_size: Tuple[int, int] = (744, 1000),
        fps: int = 15,
        include_dirs: Optional[Union[List[str], str]] = None,
        exclude_dirs: Optional[Union[List[str], str]] = None,
):

    # Log main parameters
    logger.info(f'Input dir..........: {input_dir}')
    logger.info(f'Included dirs......: {include_dirs}')
    logger.info(f'Excluded dirs......: {exclude_dirs}')
    logger.info(f'Output dir.........: {save_dir}')
    logger.info(f'Data type..........: {data_type}')
    logger.info(f'Color map..........: {color_map}')
    logger.info(f'Apply equalization.: {apply_equalization}')
    logger.info(f'Output type........: {output_type}')
    logger.info(f'Output size........: {output_size}')
    logger.info(f'FPS................: {fps if output_type == "video" else None}')
    logger.info('')

    # Filter the list of studied directories
    study_dirs = get_dir_list(
        data_dir=input_dir,
        include_dirs=include_dirs,
        exclude_dirs=exclude_dirs,
    )

    # Get list of HSI files
    hsi_paths = get_file_list(
        src_dirs=study_dirs,
        include_template='',
        ext_list='.dat',
    )
    logger.info(f'HSI found..........: {len(hsi_paths)}')

    # Multiprocessing of HSI files
    os.makedirs(save_dir, exist_ok=True)
    num_cores = multiprocessing.cpu_count()
    processing_func = partial(
        process_hsi,
        data_type=data_type,
        color_map=color_map,
        apply_equalization=apply_equalization,
        output_type=output_type,
        output_size=output_size,
        fps=fps,
        save_dir=save_dir,
    )
    _metadata = process_map(
        processing_func,
        tqdm(hsi_paths, desc='Process hyperspectral images', unit=' HSI'),
        max_workers=num_cores,
    )
    metadata = sum(_metadata, [])

    # Save metadata as an XLSX file
    df = pd.DataFrame(metadata)
    df.sort_values('Source dir', inplace=True)
    df.sort_index(inplace=True)
    save_path = os.path.join(save_dir, 'metadata.xlsx')
    df.index += 1
    df.to_excel(
        save_path,
        sheet_name='Metadata',
        index=True,
        index_label='ID',
    )
    logger.info('')
    logger.info(f'Complete')


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Convert Hyperspectral Images')
    parser.add_argument('--input_dir', default='dataset/source', type=str)
    parser.add_argument('--include_dirs', nargs='+', default=None, type=str)
    parser.add_argument('--exclude_dirs', nargs='+', default=None, type=str)
    parser.add_argument('--data_type',  default='absorbance', type=str, choices=['absorbance', 'reflectance'])
    parser.add_argument('--color_map', default=None, type=str, choices=['jet', 'bone', 'ocean', 'cool', 'hsv'])
    parser.add_argument('--apply_equalization', action='store_true')
    parser.add_argument('--output_type', default='image', type=str, choices=['image', 'video'])
    parser.add_argument('--output_size', default=[744, 1000], nargs='+', type=int)
    parser.add_argument('--fps', default=15, type=int)
    parser.add_argument('--save_dir', default='dataset/absorbance', type=str)
    args = parser.parse_args()

    main(
        input_dir=args.input_dir,
        include_dirs=args.include_dirs,
        exclude_dirs=args.exclude_dirs,
        data_type=args.data_type,
        color_map=args.color_map,
        apply_equalization=args.apply_equalization,
        output_type=args.output_type,
        output_size=tuple(args.output_size),
        fps=args.fps,
        save_dir=args.save_dir,
    )
