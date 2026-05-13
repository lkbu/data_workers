def read_sql_script(file_path):
    """
    Reads the content of a .sql file and returns it as a string.
    
    :param file_path: The path to the .sql file.
    :return: The content of the file as a string.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()