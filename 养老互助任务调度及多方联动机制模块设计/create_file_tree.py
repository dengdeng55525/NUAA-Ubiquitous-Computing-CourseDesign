import os


def get_tree_directory(path: str, prefix=""):

    # 获取当前目录下所有的文件和文件夹
    file_list = os.listdir(path)

    for index, file in enumerate(file_list):

            # 判断当前目录下的最后一个节点（无论是文件还是目录对象）
        is_last = index == len(file_list) - 1

        label = "└──" if is_last else "├──"
        print(f'{prefix}{label}{file}')

        # 尝试组合新的路径目录
        new_path = os.path.join(path, file)

        if os.path.isdir(new_path):
            # 设置层级递进规则，递归调用
            new_prefix = prefix + "    " if is_last else  prefix +"|    "
            get_tree_directory(new_path, new_prefix)


if __name__ == '__main__':

    path_input = r'C:\Users\Dengdeng\OneDrive\桌面\162330318-丁俊泽-普适计算课程设计' # 手动填写需要打印成 Tree 结构的路径 ,使用原始字符串(推荐)
    get_tree_directory(path_input)
