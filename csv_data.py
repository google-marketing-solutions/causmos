import csv

def get_csv_data(file):
    fstring = file.read().decode("utf8")
    csv_data = {}
    csv_data = [{k: v for k, v in row.items()} for row in
        csv.DictReader(fstring.splitlines(), skipinitialspace=True)]
    
    return csv_data

def get_csv_columns(data):
    keys_list = list(data[0].keys())
    date_column = ""
    for key in keys_list:
        if "date" in key:
            date_column=key
            break
    return keys_list, date_column

def csv_get_date_range(data, date_column):
    date_list = []
    for item in data:
        if date_column in item:
            date_list.append(item[date_column])
    return min(date_list), max(date_list)

def csv_merge_data(csv_data, csv_settings, raw_data):
    for item in csv_data:
        if item[csv_settings['date_column']] in raw_data:
            for col in csv_settings['metrics']:
                raw_data[item[csv_settings['date_column']]].update({f"csv_{col}": item[col]})
        else:
            for col in csv_settings['metrics']:
                if item[csv_settings['date_column']] in raw_data:
                    raw_data[item[csv_settings['date_column']]].update({f"csv_{col}": item[col]})
                else:
                    raw_data[item[csv_settings['date_column']]] = ({f"csv_{col}": item[col]})
    
    return raw_data