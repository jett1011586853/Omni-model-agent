import zipfile
import os

# 源文件夹路径
source_folder = r'D:\minimax'
# 目标 zip 文件路径（当前工作目录）
output_zip = os.path.join(os.getcwd(), 'minimax1.zip')

# 创建 zip 文件
with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(source_folder):
        for file in files:
            file_path = os.path.join(root, file)
            # 计算在 zip 中的相对路径
            arcname = os.path.relpath(file_path, os.path.dirname(source_folder))
            zipf.write(file_path, arcname)
            print(f'Added: {arcname}')

print(f'压缩包已创建: {output_zip}')
