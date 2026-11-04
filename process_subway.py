import xml.etree.ElementTree as ET
import json
from pathlib import Path
from collections import defaultdict

def process_subway_xml(input_path, output_dir):
    tree = ET.parse(input_path)
    root = tree.getroot()
    items = root.findall('.//item')

    grouped = defaultdict(lambda: [0] * 24)
    business_day = None

    for item in items:
        business_day = item.find('businessDay').text
        station_no = item.find('stationNo').text
        entry_flag = item.find('entryFlag').text
        key = (business_day, station_no, entry_flag)

        for h in range(24):
            cnt_elem = item.find(f'cnt{h:02d}')
            if cnt_elem is not None and cnt_elem.text:
                val = int(cnt_elem.text)
                grouped[key][h] += val

    if business_day:
        date_str = f"{business_day[:4]}-{business_day[4:6]}-{business_day[6:8]}"
        
        stations = {}
        for station in range(101, 123):
            station_str = str(station)
            hours_to_include = [0, 5] + list(range(6, 24))
            boardings = {str(h): grouped[(business_day, station_str, '0')][h] for h in hours_to_include}
            alightings = {str(h): grouped[(business_day, station_str, '1')][h] for h in hours_to_include}
            stations[station_str] = {
                'boardings': boardings,
                'alightings': alightings
            }

        result = {
            'date': date_str,
            'stations': stations
        }

        output_path = output_dir / f"{date_str}.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Saved: {output_path}")

if __name__ == '__main__':
    input_dir = Path('data/raw/subway')
    output_dir = Path('data/processed/subway')
    xml_files = sorted(input_dir.glob('*.xml'))
    
    for xml_file in xml_files:
        try:
            process_subway_xml(xml_file, output_dir)
        except Exception as e:
            print(f"\nError processing {xml_file.name}: {e}")
            break