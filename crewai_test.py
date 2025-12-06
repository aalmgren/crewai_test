"""
CrewAI System for Drilling Data Analysis
Reconhece tipos de arquivos e colunas obrigatórias para furos de sondagem
Usa OpenAI API
"""

import os
import sys
import json
import re
import pandas as pd
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, LLM, Process
from token_tracker import add_usage, get_current_stats

# Configurar encoding UTF-8 para Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Carregar variáveis de ambiente
load_dotenv()

# Configuração do LLM - OpenAI
def create_llm():
    """Cria instância do LLM usando OpenAI"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY nao encontrada no arquivo .env")
    
    # Usando GPT-3.5-turbo - modelo que funciona na sua conta
    return LLM(
        model="gpt-3.5-turbo",  # Modelo disponível e funcional
        temperature=0.2,
    )


def estimate_tokens(text):
    """Estimate token count (rough approximation: 1 token ≈ 4 characters)"""
    if not text:
        return 0
    return len(str(text)) // 4


def load_heuristics():
    """Load file type identification heuristics"""
    try:
        with open("file_type_heuristics.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("WARNING: file_type_heuristics.json not found. Using basic heuristics.")
        return None
    except Exception as e:
        print(f"WARNING: Error loading heuristics: {e}")
        return None


def discover_files(data_dir="data"):
    """Descobre arquivos CSV na pasta data"""
    files = {}
    if os.path.exists(data_dir):
        for filename in os.listdir(data_dir):
            if filename.endswith('.csv'):
                file_key = filename.replace('.csv', '').lower()
                files[file_key] = os.path.join(data_dir, filename)
    return files


def analyze_csv_structure(file_path):
    """Analyze CSV structure with detailed characteristics"""
    try:
        df = pd.read_csv(file_path, nrows=100)  # Read first 100 rows for analysis
        
        analysis = {
            "filename": os.path.basename(file_path),
            "rows": len(df),
            "columns": list(df.columns),
            "column_types": {},
            "sample_data": {},
            "column_stats": {}  # New: statistics for each column
        }
        
        for col in df.columns:
            analysis["column_types"][col] = str(df[col].dtype)
            # Get sample values
            sample_vals = df[col].dropna().head(3).tolist()
            analysis["sample_data"][col] = [str(v) for v in sample_vals]
            
            # Calculate statistics for better identification
            col_data = df[col].dropna()
            if len(col_data) > 0:
                unique_count = col_data.nunique()
                total_count = len(col_data)
                uniqueness_ratio = unique_count / total_count if total_count > 0 else 0
                
                # Get value range for numeric columns
                value_range = None
                if pd.api.types.is_numeric_dtype(df[col]):
                    try:
                        value_range = [float(col_data.min()), float(col_data.max())]
                    except:
                        pass
                
                analysis["column_stats"][col] = {
                    "unique_count": unique_count,
                    "total_count": total_count,
                    "uniqueness_ratio": round(uniqueness_ratio, 3),
                    "value_range": value_range,
                    "is_numeric": pd.api.types.is_numeric_dtype(df[col]),
                    "is_categorical": col_data.nunique() < total_count * 0.1 and total_count > 10  # Less than 10% unique = likely categorical
                }
        
        return analysis
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# AGENTS
# ============================================================================

def create_file_type_agent(llm_instance):
    """Agente especializado em identificar tipos de arquivos de sondagem"""
    return Agent(
        role="File Type Classifier",
        goal="Identify the type of drilling/mining data file based on structure and column names",
        backstory="""You are an expert in mining and drilling data formats.
        You know common file types like: assay (teores), lithology (litologia), 
        survey (dados de sondagem), collar (cabeçalho de furos), etc.
        You analyze file structure, column names, and sample data to classify files.""",
        llm=llm_instance,
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def create_column_identifier_agent(llm_instance):
    """Agente especializado em identificar colunas obrigatórias"""
    return Agent(
        role="Required Column Identifier",
        goal="Identify mandatory columns for drilling hole data: hole name, dip, azimuth, grade/assay columns, coordinates",
        backstory="""You are a geostatistics expert specializing in drilling data from mineral resources evaluation databases.
        You identify required columns for drilling hole data using detailed heuristics and patterns.
        You use column name patterns, data ranges, validation rules, and context to identify columns.
        All column name patterns and validation rules are provided in the task description.""",
        llm=llm_instance,
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def create_validator_agent(llm_instance):
    """Agente que valida e consolida as identificações"""
    return Agent(
        role="Data Validator",
        goal="Validate and consolidate column identifications from previous analysis",
        backstory="""You are a quality assurance specialist for drilling data.
        You review identifications made by other agents and ensure consistency.
        You check if all required columns were found and if the identifications make sense.""",
        llm=llm_instance,
        verbose=True,
        allow_delegation=False,
        max_iter=1,
    )


# ============================================================================
# TASKS
# ============================================================================

def create_file_type_task(agent, analysis, heuristics=None):
    """Task to identify file type using detailed heuristics"""
    
    columns_str = ", ".join(analysis["columns"][:15])
    sample_info = "\n".join([
        f"  {col}: {analysis['column_types'].get(col, 'unknown')} - Examples: {', '.join(analysis['sample_data'].get(col, [])[:3])}"
        for col in analysis["columns"][:8]
    ])
    
    if heuristics:
        # Build detailed description with heuristics
        heuristics_text = "\n\nDETAILED HEURISTICS FOR EACH FILE TYPE:\n"
        for file_type, info in heuristics["file_types"].items():
            heuristics_text += f"\n{file_type}:\n"
            heuristics_text += f"  Description: {info['description']}\n"
            heuristics_text += f"  Structure: {info['characteristics']['structure']}\n"
            heuristics_text += f"  Required columns:\n"
            
            for col_type, col_info in info['characteristics']['required_columns'].items():
                if not isinstance(col_info, dict):
                    continue
                    
                if 'names' in col_info:
                    heuristics_text += f"    - {col_type}: {', '.join(col_info['names'][:8])}\n"
                    if 'range' in col_info:
                        heuristics_text += f"      Range: {col_info['range']}\n"
                    if 'validation' in col_info:
                        heuristics_text += f"      Validation: {col_info['validation']}\n"
                elif 'common_names' in col_info:
                    # For coordinates
                    heuristics_text += f"    - {col_type} (3 required):\n"
                    for coord_type, names in col_info['common_names'].items():
                        heuristics_text += f"      {coord_type}: {', '.join(names[:5])}\n"
                elif 'from' in col_info or 'to' in col_info:
                    # For depth intervals (can be dict with 'names' or direct list)
                    heuristics_text += f"    - {col_type}:\n"
                    if 'from' in col_info:
                        from_val = col_info['from']
                        if isinstance(from_val, dict) and 'names' in from_val:
                            heuristics_text += f"      from: {', '.join(from_val['names'][:5])}\n"
                        elif isinstance(from_val, list):
                            heuristics_text += f"      from: {', '.join(from_val[:5])}\n"
                    if 'to' in col_info:
                        to_val = col_info['to']
                        if isinstance(to_val, dict) and 'names' in to_val:
                            heuristics_text += f"      to: {', '.join(to_val['names'][:5])}\n"
                        elif isinstance(to_val, list):
                            heuristics_text += f"      to: {', '.join(to_val[:5])}\n"
                    if 'validation' in col_info:
                        heuristics_text += f"      Validation: {col_info['validation']}\n"
                elif 'common_elements' in col_info:
                    # For element columns
                    heuristics_text += f"    - {col_type}: Chemical elements like {', '.join(col_info['common_elements'][:10])}\n"
                    if 'compound_patterns' in col_info:
                        heuristics_text += f"      Patterns: {', '.join(col_info['compound_patterns'][:5])}\n"
            
            if 'validation_rules' in info['characteristics']:
                heuristics_text += f"  Validation rules:\n"
                for rule_name, rule_desc in info['characteristics']['validation_rules'].items():
                    heuristics_text += f"    - {rule_name}: {rule_desc}\n"
        
        description = f"""Analyze this CSV file from a MINERAL RESOURCES EVALUATION database and identify its type.

CONTEXT: {heuristics['context']['description']}

FILE: {analysis['filename']}
ROWS: {analysis['rows']}
COLUMNS ({len(analysis['columns'])}): {columns_str}

COLUMN DETAILS:
{sample_info}
{heuristics_text}

YOUR TASK:
1. Analyze the file structure and column names against the detailed heuristics above
2. Check validation rules (ranges, data types, patterns)
3. Identify the most likely file type with high confidence
4. Explain your reasoning based on:
   - Column name matches to common patterns (see heuristics above)
   - Data type validation
   - Value range validation (check ranges in heuristics above)
   - File structure (one row per hole vs multiple rows)
   - Presence of required columns

OUTPUT FORMAT:
FILE TYPE: [type name]
CONFIDENCE: [high/medium/low]
REASONING: [detailed explanation using heuristics]
USE CASE: [what this file is used for in mineral resources evaluation]"""
    else:
        # Fallback to basic description
        description = f"""Analyze this CSV file and identify its type.

FILE: {analysis['filename']}
ROWS: {analysis['rows']}
COLUMNS ({len(analysis['columns'])}): {columns_str}

COLUMN DETAILS:
{sample_info}
{heuristics_text}

YOUR TASK:
1. Identify the most likely file type
2. Explain why (based on column names and sample data)
3. Suggest what this file is typically used for

OUTPUT FORMAT:
FILE TYPE: [type name]
CONFIDENCE: [high/medium/low]
REASONING: [brief explanation]
USE CASE: [what this file is used for]"""

    return Task(
        description=description,
        agent=agent,
        expected_output="File type identification with detailed reasoning based on heuristics"
    )


def extract_file_type_from_result(file_type_result_str):
    """Extract file type name from CrewAI result string"""
    if not file_type_result_str:
        return None
    
    # Look for "FILE TYPE: [type]" pattern
    match = re.search(r'FILE TYPE:\s*(\w+)', file_type_result_str, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Try to find any of the known file types in the string
    known_types = ["Collar", "Survey", "Assay", "Lithology", "Density"]
    file_type_result_lower = file_type_result_str.lower()
    for file_type in known_types:
        if file_type.lower() in file_type_result_lower:
            return file_type
    
    return None


def get_required_columns_for_file_type(file_type, heuristics):
    """Get required columns for a specific file type from heuristics"""
    if not heuristics or not file_type:
        return {}
    
    file_type_key = None
    # Find matching file type (case-insensitive)
    for key in heuristics["file_types"].keys():
        if key.lower() == file_type.lower():
            file_type_key = key
            break
    
    if not file_type_key:
        return {}
    
    file_info = heuristics["file_types"][file_type_key]
    return file_info['characteristics']['required_columns']


def extract_column_info_from_heuristics(heuristics):
    """Extract all column information from heuristics JSON"""
    if not heuristics:
        return {}
    
    column_info = {
        "hole_id": {"names": [], "type": "", "characteristics": ""},
        "dip": {"names": [], "range": [], "validation": "", "type": ""},
        "azimuth": {"names": [], "range": [], "validation": "", "type": ""},
        "coordinates": {"x": [], "y": [], "z": []},
        "elements": {"common": [], "patterns": []},
        "depth_intervals": {"from": [], "to": []}
    }
    
    # Extract from all file types
    for file_type, info in heuristics["file_types"].items():
        for col_type, col_data in info['characteristics']['required_columns'].items():
            if col_type == "hole_id" and isinstance(col_data, dict) and 'names' in col_data:
                column_info["hole_id"]["names"].extend(col_data['names'])
                if 'type' in col_data:
                    column_info["hole_id"]["type"] = col_data['type']
                if 'characteristics' in col_data:
                    column_info["hole_id"]["characteristics"] = col_data['characteristics']
            
            elif col_type == "dip" and isinstance(col_data, dict) and 'names' in col_data:
                column_info["dip"]["names"].extend(col_data['names'])
                if 'range' in col_data:
                    column_info["dip"]["range"] = col_data['range']
                if 'validation' in col_data:
                    column_info["dip"]["validation"] = col_data['validation']
                if 'type' in col_data:
                    column_info["dip"]["type"] = col_data['type']
            
            elif col_type == "azimuth" and isinstance(col_data, dict) and 'names' in col_data:
                column_info["azimuth"]["names"].extend(col_data['names'])
                if 'range' in col_data:
                    column_info["azimuth"]["range"] = col_data['range']
                if 'validation' in col_data:
                    column_info["azimuth"]["validation"] = col_data['validation']
                if 'type' in col_data:
                    column_info["azimuth"]["type"] = col_data['type']
            
            elif col_type == "coordinates" and isinstance(col_data, dict) and 'common_names' in col_data:
                for coord_type, names in col_data['common_names'].items():
                    if coord_type in column_info["coordinates"]:
                        column_info["coordinates"][coord_type].extend(names)
            
            elif col_type == "element_columns" and isinstance(col_data, dict):
                if 'common_elements' in col_data:
                    column_info["elements"]["common"].extend(col_data['common_elements'])
                if 'compound_patterns' in col_data:
                    column_info["elements"]["patterns"].extend(col_data['compound_patterns'])
            
            elif col_type == "depth_intervals" and isinstance(col_data, dict):
                if 'from' in col_data:
                    from_val = col_data['from']
                    if isinstance(from_val, dict) and 'names' in from_val:
                        column_info["depth_intervals"]["from"].extend(from_val['names'])
                    elif isinstance(from_val, list):
                        column_info["depth_intervals"]["from"].extend(from_val)
                if 'to' in col_data:
                    to_val = col_data['to']
                    if isinstance(to_val, dict) and 'names' in to_val:
                        column_info["depth_intervals"]["to"].extend(to_val['names'])
                    elif isinstance(to_val, list):
                        column_info["depth_intervals"]["to"].extend(to_val)
    
    # Remove duplicates and keep order
    for key in column_info:
        if isinstance(column_info[key], dict):
            for subkey in column_info[key]:
                if isinstance(column_info[key][subkey], list):
                    column_info[key][subkey] = list(dict.fromkeys(column_info[key][subkey]))
    
    return column_info


def create_column_identification_task(agent, analysis, file_type_result, heuristics=None, common_columns=None):
    """Task to identify required columns - ADAPTED to file type"""
    
    columns_str = ", ".join(analysis["columns"])
    sample_info = "\n".join([
        f"  {col}: Type={analysis['column_types'].get(col, 'unknown')}, Samples={', '.join(analysis['sample_data'].get(col, [])[:3])}"
        for col in analysis["columns"][:10]
    ])
    
    # Add column statistics for better identification
    stats_info = ""
    if 'column_stats' in analysis:
        stats_info = "\n".join([
            f"  {col}: Unique={analysis['column_stats'].get(col, {}).get('unique_count', 'N/A')}/{analysis['column_stats'].get(col, {}).get('total_count', 'N/A')} "
            f"(ratio={analysis['column_stats'].get(col, {}).get('uniqueness_ratio', 0):.2f}), "
            f"Range={analysis['column_stats'].get(col, {}).get('value_range', 'N/A')}, "
            f"Numeric={analysis['column_stats'].get(col, {}).get('is_numeric', False)}"
            for col in analysis["columns"][:10] if col in analysis.get('column_stats', {})
        ])
    if not stats_info:
        stats_info = "  (Statistics not available)"
    
    if heuristics:
        # Extract file type from result
        detected_file_type = extract_file_type_from_result(file_type_result)
        
        # Get required columns ONLY for this specific file type
        required_cols = get_required_columns_for_file_type(detected_file_type, heuristics) if detected_file_type else {}
        
        # Build column guide for the specific file type
        column_guide = ""
        if detected_file_type and detected_file_type in heuristics["file_types"]:
            file_info = heuristics["file_types"][detected_file_type]
            column_guide = f"\n\nREQUIRED COLUMNS FOR {detected_file_type.upper()} FILE:\n\n"
            
            for col_type, col_data in required_cols.items():
                if isinstance(col_data, dict):
                    if 'names' in col_data:
                        column_guide += f"  - {col_type}: {', '.join(col_data['names'])}\n"
                        if 'range' in col_data:
                            column_guide += f"    Range: {col_data['range']}\n"
                        if 'validation' in col_data:
                            column_guide += f"    Validation: {col_data['validation']}\n"
                        if 'type' in col_data:
                            column_guide += f"    Type: {col_data['type']}\n"
                        if 'characteristics' in col_data:
                            column_guide += f"    Characteristics: {col_data['characteristics']}\n"
                    elif 'common_names' in col_data:
                        column_guide += f"  - {col_type} (3 required - X, Y, Z coordinates):\n"
                        for coord_type, names in col_data['common_names'].items():
                            column_guide += f"    {coord_type.upper()}: {', '.join(names)}\n"
                        if 'type' in col_data:
                            column_guide += f"    Type: {col_data['type']}\n"
                        if 'characteristics' in col_data:
                            column_guide += f"    Characteristics: {col_data['characteristics']}\n"
                    elif 'from' in col_data or 'to' in col_data:
                        column_guide += f"  - {col_type} (depth intervals):\n"
                        if 'from' in col_data:
                            from_val = col_data['from']
                            if isinstance(from_val, dict) and 'names' in from_val:
                                column_guide += f"    FROM: {', '.join(from_val['names'])}\n"
                                if 'range' in from_val:
                                    column_guide += f"      Range: {from_val['range']}\n"
                            elif isinstance(from_val, list):
                                column_guide += f"    FROM: {', '.join(from_val)}\n"
                        if 'to' in col_data:
                            to_val = col_data['to']
                            if isinstance(to_val, dict) and 'names' in to_val:
                                column_guide += f"    TO: {', '.join(to_val['names'])}\n"
                                if 'range' in to_val:
                                    column_guide += f"      Range: {to_val['range']}\n"
                            elif isinstance(to_val, list):
                                column_guide += f"    TO: {', '.join(to_val)}\n"
                        if 'validation' in col_data:
                            column_guide += f"    Validation: {col_data['validation']}\n"
                    elif 'common_elements' in col_data:
                        column_guide += f"  - {col_type}:\n"
                        column_guide += f"    Common elements: {', '.join(col_data['common_elements'][:20])}\n"
                        if 'compound_patterns' in col_data:
                            column_guide += f"    Patterns: {', '.join(col_data['compound_patterns'][:10])}\n"
                        if 'type' in col_data:
                            column_guide += f"    Type: {col_data['type']}\n"
                        if 'range' in col_data:
                            column_guide += f"    Range: {col_data['range']}\n"
                        if 'characteristics' in col_data:
                            column_guide += f"    Characteristics: {col_data['characteristics']}\n"
        
        # Build required columns section - ONLY for this file type
        required_sections = []
        output_format_lines = []
        
        # Always include hole_id
        if 'hole_id' in required_cols:
            hole_data = required_cols['hole_id']
            hole_names = ', '.join(hole_data['names']) if 'names' in hole_data else "See guide above"
            hole_type = hole_data.get('type', 'categorical/text')
            hole_char = hole_data.get('characteristics', 'Unique hole identifier')
            required_sections.append(f"1. HOLE NAME/ID: {hole_char}\n   - Common names: {hole_names}\n   - Type: {hole_type}")
            output_format_lines.append("HOLE NAME: [column name or \"NOT FOUND\"] (confidence: [level]) - [reasoning]")
        
        # Include dip only if required for this file type
        if 'dip' in required_cols:
            dip_data = required_cols['dip']
            dip_names = ', '.join(dip_data['names']) if 'names' in dip_data else "See guide above"
            dip_range = f"{dip_data['range']}" if 'range' in dip_data else "-90 to 90"
            dip_validation = dip_data.get('validation', 'Values between -90 and 90 degrees')
            dip_type = dip_data.get('type', 'numeric')
            required_sections.append(f"2. DIP (Mergulho): Hole inclination angle\n   - Common names: {dip_names}\n   - Range: {dip_range} degrees\n   - Validation: {dip_validation}\n   - Type: {dip_type}\n   - NOTE: DIP can be negative (range -90 to 90)")
            output_format_lines.append("DIP: [column name or \"NOT FOUND\"] (confidence: [level]) - [reasoning]")
        
        # Include azimuth only if required for this file type
        if 'azimuth' in required_cols:
            az_data = required_cols['azimuth']
            az_names = ', '.join(az_data['names']) if 'names' in az_data else "See guide above"
            az_range = f"{az_data['range']}" if 'range' in az_data else "0 to 360"
            az_validation = az_data.get('validation', 'Values between 0 and 360 degrees')
            az_type = az_data.get('type', 'numeric')
            required_sections.append(f"3. AZIMUTH: Direction/bearing of the hole\n   - Common names: {az_names}\n   - Range: {az_range} degrees\n   - Validation: {az_validation}\n   - Type: {az_type}\n   - NOTE: BRG/Bearing are common abbreviations for azimuth")
            output_format_lines.append("AZIMUTH: [column name or \"NOT FOUND\"] (confidence: [level]) - [reasoning]")
        
        # Include depth only if required for this file type (Survey)
        if 'depth' in required_cols:
            depth_data = required_cols['depth']
            depth_names = ', '.join(depth_data['names']) if 'names' in depth_data else "See guide above"
            depth_range = f"{depth_data['range']}" if 'range' in depth_data else "0 to 10000"
            depth_validation = depth_data.get('validation', 'Depth where measurement was taken')
            depth_type = depth_data.get('type', 'numeric')
            depth_char = depth_data.get('characteristics', 'Depth where measurement was taken')
            section_num = len(required_sections) + 1
            required_sections.append(f"{section_num}. DEPTH (AT): {depth_char}\n   - Common names: {depth_names}\n   - Range: {depth_range}\n   - Validation: {depth_validation}\n   - Type: {depth_type}")
            output_format_lines.append("DEPTH (AT): [column name or \"NOT FOUND\"] (confidence: [level]) - [reasoning]")
        
        # Include coordinates only if required for this file type
        if 'coordinates' in required_cols:
            coord_data = required_cols['coordinates']
            if 'common_names' in coord_data:
                coord_x = ', '.join(coord_data['common_names'].get('x', []))
                coord_y = ', '.join(coord_data['common_names'].get('y', []))
                coord_z = ', '.join(coord_data['common_names'].get('z', []))
                coord_type = coord_data.get('type', 'numeric')
                coord_char = coord_data.get('characteristics', 'Spatial coordinates')
                section_num = len(required_sections) + 1
                required_sections.append(f"{section_num}. COORDINATES: {coord_char}\n   - X/East: {coord_x}\n   - Y/North: {coord_y}\n   - Z/Elevation: {coord_z}\n   - Type: {coord_type}\n   - Numeric, usually large values (UTM coordinates)")
                output_format_lines.append("COORDINATES: X=[name], Y=[name], Z=[name] (confidence: [level]) - [reasoning]")
        
        # Include element_columns only if required for this file type (Assay)
        if 'element_columns' in required_cols:
            elem_data = required_cols['element_columns']
            elements = ', '.join(elem_data.get('common_elements', [])[:20])
            patterns = ', '.join(elem_data.get('compound_patterns', [])[:10])
            section_num = len(required_sections) + 1
            required_sections.append(f"{section_num}. GRADE/ASSAY COLUMNS: Element concentrations\n   - Common elements: {elements}\n   - Patterns: {patterns if patterns else 'See guide above'}\n   - Usually numeric, values in ppm, %, g/t, or similar units")
            output_format_lines.append("GRADE COLUMNS: [list of column names] (confidence: [level]) - [reasoning]")
        
        # Include depth_intervals only if required for this file type
        if 'depth_intervals' in required_cols:
            depth_data = required_cols['depth_intervals']
            section_num = len(required_sections) + 1
            from_names = []
            to_names = []
            if 'from' in depth_data:
                from_val = depth_data['from']
                if isinstance(from_val, dict) and 'names' in from_val:
                    from_names = from_val['names']
                elif isinstance(from_val, list):
                    from_names = from_val
            if 'to' in depth_data:
                to_val = depth_data['to']
                if isinstance(to_val, dict) and 'names' in to_val:
                    to_names = to_val['names']
                elif isinstance(to_val, list):
                    to_names = to_val
            required_sections.append(f"{section_num}. DEPTH INTERVALS:\n   - FROM: {', '.join(from_names)}\n   - TO: {', '.join(to_names)}\n   - Validation: {depth_data.get('validation', 'TO must be greater than FROM')}")
            output_format_lines.append("DEPTH INTERVALS: FROM=[name], TO=[name] (confidence: [level]) - [reasoning]")
        
        # Include lithology_code only if required for this file type (Lithology)
        if 'lithology_code' in required_cols:
            lith_data = required_cols['lithology_code']
            section_num = len(required_sections) + 1
            lith_names = ', '.join(lith_data.get('names', []))
            lith_type = lith_data.get('type', 'categorical')
            lith_char = lith_data.get('characteristics', 'Rock type classification')
            required_sections.append(f"{section_num}. LITHOLOGY CODE: {lith_char}\n   - Common names: {lith_names}\n   - Type: {lith_type}")
            output_format_lines.append("LITHOLOGY CODE: [column name or \"NOT FOUND\"] (confidence: [level]) - [reasoning]")
        
        # Include density only if required for this file type (Density)
        if 'density' in required_cols:
            dens_data = required_cols['density']
            section_num = len(required_sections) + 1
            dens_names = ', '.join(dens_data.get('names', []))
            dens_range = f"{dens_data['range']}" if 'range' in dens_data else "1.0 to 10.0"
            dens_validation = dens_data.get('validation', 'Typical values between 1.5 and 5.0 g/cm³')
            dens_type = dens_data.get('type', 'numeric')
            required_sections.append(f"{section_num}. DENSITY: {dens_data.get('characteristics', 'Density in g/cm³')}\n   - Common names: {dens_names}\n   - Range: {dens_range} g/cm³\n   - Validation: {dens_validation}\n   - Type: {dens_type}")
            output_format_lines.append("DENSITY: [column name or \"NOT FOUND\"] (confidence: [level]) - [reasoning]")
        
        required_sections_text = "\n\n".join(required_sections)
        output_format_text = "\n".join(output_format_lines)
        
        # Build cross-reference info
        cross_ref_info = ""
        if common_columns:
            cross_ref_info = "\n\nCROSS-REFERENCE ANALYSIS (columns appearing in multiple files - likely hole_id):\n"
            for col_name, info in common_columns.items():
                if col_name in analysis["columns"]:
                    cross_ref_info += f"  - {col_name}: Appears in {info['count']} files ({', '.join(info['files'])})\n"
                    cross_ref_info += f"    This column appears in multiple files, which is a strong indicator it's the hole_id\n"
        
        description = f"""Identify required columns for this {detected_file_type if detected_file_type else 'drilling data'} file from MINERAL RESOURCES EVALUATION database.

FILE: {analysis['filename']}
FILE TYPE (from previous analysis): {file_type_result}
{column_guide}

ALL COLUMNS ({len(analysis['columns'])}):
{columns_str}

COLUMN DETAILS:
{sample_info}

COLUMN STATISTICS (for identification by characteristics, not just names):
{stats_info}
{cross_ref_info}

REQUIRED COLUMNS TO FIND FOR THIS FILE TYPE:
{required_sections_text}

YOUR TASK:
For each required column type listed above, identify:
- Which column(s) match (if any) - BE CAREFUL: check ALL column names against the patterns above
- Confidence level (high/medium/low)
- Reasoning based on name patterns AND data characteristics (ranges, types, uniqueness, structure)

CRITICAL IDENTIFICATION RULES (use these even if column name is NOT in the common names list):

1. HOLE ID identification:
   - If file type is Collar: Look for column with HIGH uniqueness ratio (close to 1.0) - one unique value per row
   - If file type is Survey/Assay/Lithology: Look for column that appears multiple times (lower uniqueness, but categorical)
   - Check if column values match patterns like: alphanumeric codes (DH0001, BH-001, etc.)
   - Type should be categorical/text/object
   - Even if name is completely new, if it has these characteristics, it's likely the hole_id

2. COORDINATES identification:
   - Look for 3 numeric columns with large values (thousands for X/Y, tens/hundreds for Z)
   - Check if values are in reasonable coordinate ranges
   - Even if names are X_UNKNOWN, Y_UNKNOWN, Z_UNKNOWN, if they have these characteristics, they're coordinates

3. DIP/AZIMUTH identification:
   - DIP: Numeric column with values between -90 and 90
   - AZIMUTH: Numeric column with values between 0 and 360
   - Even if names are completely new, if ranges match, identify them

4. GRADE COLUMNS identification:
   - Look for numeric columns with element-like names OR small positive values (ppm, %, g/t ranges)
   - Check if column names contain chemical symbols or element abbreviations
   - Even if element name is new, if it's numeric and in reasonable grade ranges, it's likely a grade column

5. DEPTH INTERVALS identification:
   - Look for two numeric columns where one is always less than the other
   - Values should be positive and increasing
   - Even if names are FROM_UNKNOWN, TO_UNKNOWN, if they have this relationship, they're depth intervals

IMPORTANT:
- Check column names case-insensitively
- XCOLLAR = X coordinate, YCOLLAR = Y coordinate, ZCOLLAR = Z coordinate
- BRG/Bearing = Azimuth (same thing)
- DIP can be negative (range -90 to 90)
- Verify data ranges match expected ranges
- USE DATA CHARACTERISTICS, not just names - if characteristics match, identify the column even if name is new
- If a column type is NOT listed above, it means it's NOT expected for this file type

OUTPUT FORMAT:
{output_format_text}"""
    else:
        # Fallback - should not happen if heuristics are loaded
        description = f"""Identify required columns for drilling hole data in this file.

FILE: {analysis['filename']}
FILE TYPE (from previous analysis): {file_type_result}

ALL COLUMNS ({len(analysis['columns'])}):
{columns_str}

COLUMN DETAILS:
{sample_info}

ERROR: Heuristics not available. Please ensure file_type_heuristics.json is present.

YOUR TASK:
Identify required columns based on column names and data characteristics.

OUTPUT FORMAT:
HOLE NAME: [column name or "NOT FOUND"] (confidence: [level]) - [reasoning]
DIP: [column name or "NOT FOUND"] (confidence: [level]) - [reasoning]
AZIMUTH: [column name or "NOT FOUND"] (confidence: [level]) - [reasoning]
GRADE COLUMNS: [list of column names] (confidence: [level]) - [reasoning]
COORDINATES: X=[name], Y=[name], Z=[name] (confidence: [level]) - [reasoning]"""

    return Task(
        description=description,
        agent=agent,
        expected_output="Identification of all required columns with confidence levels"
    )


def parse_column_identification_result(column_result_str):
    """Parse column identification result and extract structured data"""
    if not column_result_str:
        return {}
    
    result = {
        "hole_id": {"found": None, "comment": ""},
        "coordinates": {"x": None, "y": None, "z": None, "comment": ""},
        "grades": {"found": [], "comment": ""},
        "from": {"found": None, "comment": ""},
        "to": {"found": None, "comment": ""},
        "dip": {"found": None, "comment": ""},
        "azimuth": {"found": None, "comment": ""},
        "depth": {"found": None, "comment": ""},  # AT from survey
        "density": {"found": None, "comment": ""},
        "lithology": {"found": None, "comment": ""}
    }
    
    # Parse HOLE NAME
    hole_match = re.search(r'HOLE NAME:\s*([^\s(]+)', column_result_str, re.IGNORECASE)
    if hole_match:
        hole_name = hole_match.group(1).strip()
        if hole_name.upper() != "NOT" and "FOUND" not in hole_name.upper():
            result["hole_id"]["found"] = hole_name
            # Extract comment (full comment, not truncated)
            comment_match = re.search(r'HOLE NAME:.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
            if comment_match:
                result["hole_id"]["comment"] = comment_match.group(1).strip()
    
    # Parse COORDINATES - try multiple formats
    coord_match = re.search(r'COORDINATES:.*?X=([^\s,=]+),?\s*Y=([^\s,=]+),?\s*Z=([^\s(,=]+)', column_result_str, re.IGNORECASE)
    if coord_match:
        result["coordinates"]["x"] = coord_match.group(1).strip()
        result["coordinates"]["y"] = coord_match.group(2).strip()
        result["coordinates"]["z"] = coord_match.group(3).strip()
        # Extract comment (full comment)
        comment_match = re.search(r'COORDINATES:.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
        if comment_match:
            result["coordinates"]["comment"] = comment_match.group(1).strip()
    else:
        # Try to find coordinate columns individually (XCOLLAR, YCOLLAR, ZCOLLAR, etc.)
        coord_patterns = {
            'x': ['XCOLLAR', 'X', 'EAST', 'EASTING', 'X_UTM', 'XCOORD'],
            'y': ['YCOLLAR', 'Y', 'NORTH', 'NORTHING', 'Y_UTM', 'YCOORD'],
            'z': ['ZCOLLAR', 'Z', 'ELEV', 'ELEVATION', 'RL', 'Z_UTM', 'ZCOORD']
        }
        for coord_type, patterns in coord_patterns.items():
            for pattern in patterns:
                if re.search(r'\b' + re.escape(pattern) + r'\b', column_result_str, re.IGNORECASE):
                    result["coordinates"][coord_type] = pattern
                    break
    
    # Parse DIP
    dip_match = re.search(r'DIP:\s*([^\s(]+)', column_result_str, re.IGNORECASE)
    if dip_match:
        dip_name = dip_match.group(1).strip()
        if dip_name.upper() != "NOT" and "FOUND" not in dip_name.upper():
            result["dip"]["found"] = dip_name
            comment_match = re.search(r'DIP:.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
            if comment_match:
                result["dip"]["comment"] = comment_match.group(1).strip()
    
    # Parse AZIMUTH
    az_match = re.search(r'AZIMUTH:\s*([^\s(]+)', column_result_str, re.IGNORECASE)
    if az_match:
        az_name = az_match.group(1).strip()
        if az_name.upper() != "NOT" and "FOUND" not in az_name.upper():
            result["azimuth"]["found"] = az_name
            comment_match = re.search(r'AZIMUTH:.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
            if comment_match:
                result["azimuth"]["comment"] = comment_match.group(1).strip()
    
    # Parse GRADE COLUMNS - can be in format [list] or just column names
    grade_match = re.search(r'GRADE COLUMNS:\s*(?:\[([^\]]+)\]|([^\s(]+))', column_result_str, re.IGNORECASE)
    if grade_match:
        if grade_match.group(1):  # List format
            grades_str = grade_match.group(1)
            grades = [g.strip().strip('"\'') for g in grades_str.split(',') if g.strip() and 'NOT FOUND' not in g.upper()]
            result["grades"]["found"] = grades
        elif grade_match.group(2):  # Single column or comma-separated
            grades_str = grade_match.group(2)
            if 'NOT FOUND' not in grades_str.upper():
                grades = [g.strip() for g in grades_str.split(',') if g.strip()]
                result["grades"]["found"] = grades
        comment_match = re.search(r'GRADE COLUMNS:.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
        if comment_match:
            result["grades"]["comment"] = comment_match.group(1).strip()
    
    # Parse DEPTH INTERVALS (FROM/TO)
    depth_match = re.search(r'DEPTH INTERVALS:.*?FROM=([^\s,]+),?\s*TO=([^\s(]+)', column_result_str, re.IGNORECASE)
    if depth_match:
        result["from"]["found"] = depth_match.group(1).strip()
        result["to"]["found"] = depth_match.group(2).strip()
        comment_match = re.search(r'DEPTH INTERVALS:.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
        if comment_match:
            result["from"]["comment"] = comment_match.group(1).strip()
            result["to"]["comment"] = comment_match.group(1).strip()
    
    # Parse DENSITY
    dens_match = re.search(r'DENSITY:\s*([^\s(]+)', column_result_str, re.IGNORECASE)
    if dens_match:
        dens_name = dens_match.group(1).strip()
        if dens_name.upper() != "NOT" and "FOUND" not in dens_name.upper():
            result["density"]["found"] = dens_name
            comment_match = re.search(r'DENSITY:.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
            if comment_match:
                result["density"]["comment"] = comment_match.group(1).strip()
    
    # Parse LITHOLOGY
    lith_match = re.search(r'LITHOLOGY CODE:\s*([^\s(]+)', column_result_str, re.IGNORECASE)
    if lith_match:
        lith_name = lith_match.group(1).strip()
        if lith_name.upper() != "NOT" and "FOUND" not in lith_name.upper():
            result["lithology"]["found"] = lith_name
            comment_match = re.search(r'LITHOLOGY CODE:.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
            if comment_match:
                result["lithology"]["comment"] = comment_match.group(1).strip()
    
    # Parse DEPTH (AT) - can be in format "DEPTH (AT): AT" or just mentioned
    depth_at_match = re.search(r'DEPTH\s*\(AT\):\s*([^\s(]+)', column_result_str, re.IGNORECASE)
    if depth_at_match:
        depth_name = depth_at_match.group(1).strip()
        if depth_name.upper() != "NOT" and "FOUND" not in depth_name.upper():
            result["depth"]["found"] = depth_name
            comment_match = re.search(r'DEPTH\s*\(AT\):.*?-\s*(.+?)(?:\n|$)', column_result_str, re.IGNORECASE | re.DOTALL)
            if comment_match:
                result["depth"]["comment"] = comment_match.group(1).strip()
            else:
                result["depth"]["comment"] = "Depth measurement"
    else:
        # Try to find depth/AT from survey - look in the actual column list context
        # Check if AT, DEPTH, MD appear as column names in the result
        depth_cols = ['AT', 'DEPTH', 'MD', 'MEASURED_DEPTH', 'FROM_DEPTH', 'TO_DEPTH']
        for col in depth_cols:
            # Look for the column name as a standalone word (not part of another word)
            pattern = r'\b' + re.escape(col) + r'\b'
            if re.search(pattern, column_result_str, re.IGNORECASE):
                result["depth"]["found"] = col
                result["depth"]["comment"] = "Depth measurement"
                break
    
    return result


def get_relevant_fields_for_file_type(file_type):
    """Get which fields are relevant for each file type"""
    field_mapping = {
        "Collar": ["hole_id", "coordinates"],
        "Survey": ["hole_id", "dip", "azimuth", "depth"],
        "Assay": ["hole_id", "from", "to", "grades"],
        "Lithology": ["hole_id", "from", "to", "lithology"],
        "Density": ["hole_id", "from", "to", "density"]
    }
    return field_mapping.get(file_type, [])


def format_consolidated_summary(all_results, all_analyses=None):
    """Format a single consolidated table with all results - NO TRUNCATION, ALL COLUMNS"""
    lines = []
    lines.append("=" * 200)
    lines.append("CONSOLIDATED COLUMN SUMMARY")
    lines.append("=" * 200)
    lines.append(f"{'Tipo':<12} | {'Campo':<25} | {'Campo Encontrado':<30} | {'Comentário':<130}")
    lines.append("-" * 200)
    
    # Map of identified columns by field type
    identified_map = {}  # {file_type: {field_name: column_name}}
    
    for r in all_results:
        file_type = extract_file_type_from_result(r['type']) or "Unknown"
        parsed_cols = parse_column_identification_result(r.get('columns', ''))
        relevant_fields = get_relevant_fields_for_file_type(file_type)
        
        if file_type not in identified_map:
            identified_map[file_type] = {}
        
        # Map identified columns
        if "hole_id" in relevant_fields and parsed_cols.get("hole_id", {}).get("found"):
            identified_map[file_type]["Hole ID"] = parsed_cols["hole_id"]["found"]
        
        if "coordinates" in relevant_fields:
            if parsed_cols.get("coordinates", {}).get("x"):
                identified_map[file_type]["Coordinates X"] = parsed_cols["coordinates"]["x"]
            if parsed_cols.get("coordinates", {}).get("y"):
                identified_map[file_type]["Coordinates Y"] = parsed_cols["coordinates"]["y"]
            if parsed_cols.get("coordinates", {}).get("z"):
                identified_map[file_type]["Coordinates Z"] = parsed_cols["coordinates"]["z"]
        
        if "dip" in relevant_fields and parsed_cols.get("dip", {}).get("found"):
            identified_map[file_type]["DIP"] = parsed_cols["dip"]["found"]
        
        if "azimuth" in relevant_fields and parsed_cols.get("azimuth", {}).get("found"):
            identified_map[file_type]["Azimuth"] = parsed_cols["azimuth"]["found"]
        
        if "depth" in relevant_fields and parsed_cols.get("depth", {}).get("found"):
            identified_map[file_type]["Depth (AT)"] = parsed_cols["depth"]["found"]
        
        if "from" in relevant_fields and parsed_cols.get("from", {}).get("found"):
            identified_map[file_type]["FROM (depth)"] = parsed_cols["from"]["found"]
        
        if "to" in relevant_fields and parsed_cols.get("to", {}).get("found"):
            identified_map[file_type]["TO (depth)"] = parsed_cols["to"]["found"]
        
        if "grades" in relevant_fields and parsed_cols.get("grades", {}).get("found"):
            grades = parsed_cols["grades"]["found"]
            if grades:
                identified_map[file_type]["Grades"] = grades
        
        if "density" in relevant_fields and parsed_cols.get("density", {}).get("found"):
            identified_map[file_type]["Density"] = parsed_cols["density"]["found"]
        
        if "lithology" in relevant_fields and parsed_cols.get("lithology", {}).get("found"):
            identified_map[file_type]["Lithology"] = parsed_cols["lithology"]["found"]
    
    # Now add all original columns from files
    for r in all_results:
        file_type = extract_file_type_from_result(r['type']) or "Unknown"
        parsed_cols = parse_column_identification_result(r.get('columns', ''))
        relevant_fields = get_relevant_fields_for_file_type(file_type)
        
        # Get original columns from analysis
        file_key = r.get('file', '')
        original_columns = []
        if all_analyses and file_key in all_analyses:
            original_columns = all_analyses[file_key].get("columns", [])
        
        # First, show identified relevant fields
        if "hole_id" in relevant_fields:
            found = parsed_cols.get("hole_id", {}).get("found", "NOT FOUND")
            comment = parsed_cols["hole_id"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'Hole ID':<25} | {str(found):<30} | {comment:<130}")
        
        if "coordinates" in relevant_fields:
            x = parsed_cols.get("coordinates", {}).get("x", "NOT FOUND")
            y = parsed_cols.get("coordinates", {}).get("y", "NOT FOUND")
            z = parsed_cols.get("coordinates", {}).get("z", "NOT FOUND")
            comment = parsed_cols["coordinates"].get("comment", "OK") if x != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'Coordinates X':<25} | {str(x):<30} | {comment:<130}")
            lines.append(f"{file_type:<12} | {'Coordinates Y':<25} | {str(y):<30} | {'OK':<130}")
            lines.append(f"{file_type:<12} | {'Coordinates Z':<25} | {str(z):<30} | {'OK':<130}")
        
        if "dip" in relevant_fields:
            found = parsed_cols.get("dip", {}).get("found", "NOT FOUND")
            comment = parsed_cols["dip"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'DIP':<25} | {str(found):<30} | {comment:<130}")
        
        if "azimuth" in relevant_fields:
            found = parsed_cols.get("azimuth", {}).get("found", "NOT FOUND")
            comment = parsed_cols["azimuth"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'Azimuth':<25} | {str(found):<30} | {comment:<130}")
        
        if "depth" in relevant_fields:
            found = parsed_cols.get("depth", {}).get("found", "NOT FOUND")
            comment = parsed_cols["depth"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'Depth (AT)':<25} | {str(found):<30} | {comment:<130}")
        
        if "from" in relevant_fields:
            found = parsed_cols.get("from", {}).get("found", "NOT FOUND")
            comment = parsed_cols["from"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'FROM (depth)':<25} | {str(found):<30} | {comment:<130}")
        
        if "to" in relevant_fields:
            found = parsed_cols.get("to", {}).get("found", "NOT FOUND")
            comment = parsed_cols["to"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'TO (depth)':<25} | {str(found):<30} | {comment:<130}")
        
        if "grades" in relevant_fields:
            grades = parsed_cols.get("grades", {}).get("found", [])
            if grades:
                grades_str = ", ".join(grades)
                comment = parsed_cols["grades"].get("comment", "OK")
                lines.append(f"{file_type:<12} | {'Grades':<25} | {grades_str:<30} | {comment:<130}")
        
        if "density" in relevant_fields:
            found = parsed_cols.get("density", {}).get("found", "NOT FOUND")
            comment = parsed_cols["density"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'Density':<25} | {str(found):<30} | {comment:<130}")
        
        if "lithology" in relevant_fields:
            found = parsed_cols.get("lithology", {}).get("found", "NOT FOUND")
            comment = parsed_cols["lithology"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            lines.append(f"{file_type:<12} | {'Lithology':<25} | {str(found):<30} | {comment:<130}")
        
        # Now add ALL original columns that were not identified
        identified_cols = set()
        for field_type, col_name in identified_map.get(file_type, {}).items():
            if isinstance(col_name, list):
                identified_cols.update(col_name)
            else:
                identified_cols.add(col_name)
        
        # Add coordinates separately
        if parsed_cols.get("coordinates", {}).get("x"):
            identified_cols.add(parsed_cols["coordinates"]["x"])
        if parsed_cols.get("coordinates", {}).get("y"):
            identified_cols.add(parsed_cols["coordinates"]["y"])
        if parsed_cols.get("coordinates", {}).get("z"):
            identified_cols.add(parsed_cols["coordinates"]["z"])
        
        for col in original_columns:
            if col not in identified_cols:
                # This is an original column that wasn't identified as a standard field
                lines.append(f"{file_type:<12} | {col:<25} | {'(original column)':<30} | {'Column present in file but not mapped to standard field':<130}")
    
    lines.append("=" * 200)
    return "\n".join(lines)


def format_consolidated_summary_json(all_results, all_analyses=None):
    """Format consolidated summary as JSON for web interface"""
    table_rows = []
    
    for r in all_results:
        file_type = extract_file_type_from_result(r['type']) or "Unknown"
        parsed_cols = parse_column_identification_result(r.get('columns', ''))
        relevant_fields = get_relevant_fields_for_file_type(file_type)
        file_key = r.get('file', '')
        original_columns = []
        if all_analyses and file_key in all_analyses:
            original_columns = all_analyses[file_key].get("columns", [])
        
        # Collect identified columns
        identified_cols = set()
        
        # Add identified fields
        if "hole_id" in relevant_fields:
            found = parsed_cols.get("hole_id", {}).get("found", "NOT FOUND")
            comment = parsed_cols["hole_id"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "Hole ID",
                "found": str(found),
                "comment": comment
            })
            if found != "NOT FOUND":
                identified_cols.add(str(found))
        
        if "coordinates" in relevant_fields:
            x = parsed_cols.get("coordinates", {}).get("x", "NOT FOUND")
            y = parsed_cols.get("coordinates", {}).get("y", "NOT FOUND")
            z = parsed_cols.get("coordinates", {}).get("z", "NOT FOUND")
            comment = parsed_cols["coordinates"].get("comment", "OK") if x != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "Coordinates X",
                "found": str(x),
                "comment": comment
            })
            table_rows.append({
                "file_type": file_type,
                "field": "Coordinates Y",
                "found": str(y),
                "comment": "OK"
            })
            table_rows.append({
                "file_type": file_type,
                "field": "Coordinates Z",
                "found": str(z),
                "comment": "OK"
            })
            if x != "NOT FOUND":
                identified_cols.add(str(x))
            if y != "NOT FOUND":
                identified_cols.add(str(y))
            if z != "NOT FOUND":
                identified_cols.add(str(z))
        
        if "dip" in relevant_fields:
            found = parsed_cols.get("dip", {}).get("found", "NOT FOUND")
            comment = parsed_cols["dip"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "DIP",
                "found": str(found),
                "comment": comment
            })
            if found != "NOT FOUND":
                identified_cols.add(str(found))
        
        if "azimuth" in relevant_fields:
            found = parsed_cols.get("azimuth", {}).get("found", "NOT FOUND")
            comment = parsed_cols["azimuth"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "Azimuth",
                "found": str(found),
                "comment": comment
            })
            if found != "NOT FOUND":
                identified_cols.add(str(found))
        
        if "depth" in relevant_fields:
            found = parsed_cols.get("depth", {}).get("found", "NOT FOUND")
            comment = parsed_cols["depth"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "Depth (AT)",
                "found": str(found),
                "comment": comment
            })
            if found != "NOT FOUND":
                identified_cols.add(str(found))
        
        if "from" in relevant_fields:
            found = parsed_cols.get("from", {}).get("found", "NOT FOUND")
            comment = parsed_cols["from"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "FROM (depth)",
                "found": str(found),
                "comment": comment
            })
            if found != "NOT FOUND":
                identified_cols.add(str(found))
        
        if "to" in relevant_fields:
            found = parsed_cols.get("to", {}).get("found", "NOT FOUND")
            comment = parsed_cols["to"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "TO (depth)",
                "found": str(found),
                "comment": comment
            })
            if found != "NOT FOUND":
                identified_cols.add(str(found))
        
        if "grades" in relevant_fields:
            grades = parsed_cols.get("grades", {}).get("found", [])
            if grades:
                grades_str = ", ".join(grades)
                comment = parsed_cols["grades"].get("comment", "OK")
                table_rows.append({
                    "file_type": file_type,
                    "field": "Grades",
                    "found": grades_str,
                    "comment": comment
                })
                identified_cols.update(grades)
        
        if "density" in relevant_fields:
            found = parsed_cols.get("density", {}).get("found", "NOT FOUND")
            comment = parsed_cols["density"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "Density",
                "found": str(found),
                "comment": comment
            })
            if found != "NOT FOUND":
                identified_cols.add(str(found))
        
        if "lithology" in relevant_fields:
            found = parsed_cols.get("lithology", {}).get("found", "NOT FOUND")
            comment = parsed_cols["lithology"].get("comment", "OK") if found != "NOT FOUND" else "Not identified"
            table_rows.append({
                "file_type": file_type,
                "field": "Lithology",
                "found": str(found),
                "comment": comment
            })
            if found != "NOT FOUND":
                identified_cols.add(str(found))
        
        # Add original columns not identified
        for col in original_columns:
            if col not in identified_cols:
                table_rows.append({
                    "file_type": file_type,
                    "field": col,
                    "found": "(original column)",
                    "comment": "Column present in file but not mapped to standard field"
                })
    
    return table_rows


def create_validation_task(agent, file_type_result, column_result):
    """Task para validar e consolidar resultados"""
    
    description = f"""Validate and consolidate the analysis results.

FILE TYPE IDENTIFICATION:
{file_type_result}

COLUMN IDENTIFICATION:
{column_result}

YOUR TASK:
1. Review if the file type identification makes sense
2. Verify if all required columns were correctly identified
3. Check for any inconsistencies
4. Provide a final consolidated summary

OUTPUT FORMAT:
VALIDATION SUMMARY:
- File Type: [validated type] ✓/✗
- Hole Name: [status] ✓/✗
- Dip: [status] ✓/✗
- Azimuth: [status] ✓/✗
- Grade Columns: [count found] ✓/✗
- Coordinates: [status] ✓/✗

FINAL RECOMMENDATIONS:
[Any issues found or recommendations]"""

    return Task(
        description=description,
        agent=agent,
        expected_output="Validated and consolidated summary"
    )


# ============================================================================
# MAIN EXECUTION
# ============================================================================



def run_analysis(data_dir="data"):
    """Execute complete analysis using CrewAI"""
    
    print("\n" + "="*70)
    print("CREWAI - DRILLING DATA ANALYSIS")
    print("="*70)
    print("Analyzing files in:", data_dir)
    print("Using OpenAI API (GPT-3.5-turbo)")
    print("="*70 + "\n")
    
    # Load heuristics
    print("Loading file type identification heuristics...")
    heuristics = load_heuristics()
    if heuristics:
        print("Heuristics loaded successfully\n")
    else:
        print("Continuing without detailed heuristics...\n")
    
    # Create LLM instance
    print("Creating LLM instance...")
    try:
        llm_instance = create_llm()
        print("LLM created successfully")
        print(f"   Model: gpt-3.5-turbo\n")
    except Exception as e:
        print(f"ERROR creating LLM: {e}")
        print("   Verify OPENAI_API_KEY is configured in .env file")
        print(f"   Detailed error: {type(e).__name__}: {str(e)}")
        return
    
    # Descobrir arquivos
    files = discover_files(data_dir)
    
    if not files:
        print(f"ERRO: Nenhum arquivo CSV encontrado em '{data_dir}/'")
        return
    
    print(f"Encontrados {len(files)} arquivo(s):")
    for file_key in files.keys():
        print(f"  - {file_key}.csv")
    print()
    
    # Criar agentes
    print("Criando agentes especializados...")
    try:
        file_type_agent = create_file_type_agent(llm_instance)
        column_agent = create_column_identifier_agent(llm_instance)
        validator_agent = create_validator_agent(llm_instance)
        print("3 agentes criados\n")
    except Exception as e:
        print(f"ERRO ao criar agentes: {e}")
        return
    
    # First pass: Analyze all files to find common columns (cross-reference)
    print("First pass: Analyzing all files for cross-reference...")
    all_analyses = {}
    for file_key, file_path in files.items():
        analysis = analyze_csv_structure(file_path)
        if "error" not in analysis:
            all_analyses[file_key] = analysis
    
    # Find potential hole_id columns by cross-referencing
    # A column that appears in multiple files with similar values is likely hole_id
    common_columns = {}
    if len(all_analyses) > 1:
        # Get all column names from all files
        all_column_names = set()
        for analysis in all_analyses.values():
            all_column_names.update(analysis["columns"])
        
        # For each column name, check if it appears in multiple files
        for col_name in all_column_names:
            files_with_col = [f for f, a in all_analyses.items() if col_name in a["columns"]]
            if len(files_with_col) > 1:
                # This column appears in multiple files - could be hole_id
                common_columns[col_name] = {
                    "files": files_with_col,
                    "count": len(files_with_col)
                }
    
    results = []
    
    # Processar cada arquivo
    for file_key, file_path in files.items():
        print("="*70)
        print(f"PROCESSANDO: {file_key.upper()}")
        print("="*70 + "\n")
        
        # Analisar estrutura
        print("Analisando estrutura do arquivo...")
        analysis = analyze_csv_structure(file_path)
        
        if "error" in analysis:
            print(f"ERRO ao analisar: {analysis['error']}")
            continue
        
        print(f"  - {analysis['rows']} linhas")
        print(f"  - {len(analysis['columns'])} colunas: {', '.join(analysis['columns'][:5])}...")
        print()
        
        # TASK 1: Identify file type
        print("TASK 1: Identifying file type...")
        task1 = create_file_type_task(file_type_agent, analysis, heuristics)
        
        crew1 = Crew(
            agents=[file_type_agent],
            tasks=[task1],
            process=Process.sequential,
            verbose=True
        )
        
        try:
            result1 = crew1.kickoff()
            # Extrair o texto completo do resultado
            if hasattr(result1, 'raw'):
                result1_str = str(result1.raw) if result1.raw else str(result1)
            elif hasattr(result1, 'content'):
                result1_str = str(result1.content) if result1.content else str(result1)
            else:
                result1_str = str(result1) if result1 else "No result"
            print(f"\nTipo identificado:\n{result1_str}\n")
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            print(f"ERRO na Task 1: {error_msg}\n")
            print(f"   Tipo: {error_type}\n")
            result1 = "Error identifying file type - Task failed"
            print("Continuando com Task 2 mesmo com erro na Task 1...\n")
        
        # TASK 2: Identify required columns
        print("TASK 2: Identifying required columns...")
        # Use the extracted string, not the raw result object
        file_type_str = result1_str if 'result1_str' in locals() else str(result1)
        task2 = create_column_identification_task(column_agent, analysis, file_type_str, heuristics, common_columns)
        
        crew2 = Crew(
            agents=[column_agent],
            tasks=[task2],
            process=Process.sequential,
            verbose=True
        )
        
        try:
            result2 = crew2.kickoff()
            # Extract full text from result
            if hasattr(result2, 'raw'):
                result2_str = str(result2.raw) if result2.raw else str(result2)
            elif hasattr(result2, 'content'):
                result2_str = str(result2.content) if result2.content else str(result2)
            elif hasattr(result2, '__str__'):
                result2_str = str(result2)
            else:
                result2_str = repr(result2) if result2 else "No result"
            print(f"\nColunas identificadas:\n{result2_str}\n")
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            print(f"ERRO na Task 2: {error_msg}\n")
            print(f"   Tipo: {error_type}\n")
            result2 = "Error identifying columns - Task failed"
            print("Continuando com Task 3 mesmo com erro na Task 2...\n")
        
        # TASK 3: Validar resultados
        print("TASK 3: Validando e consolidando resultados...")
        task3 = create_validation_task(validator_agent, result1, result2)
        
        crew3 = Crew(
            agents=[validator_agent],
            tasks=[task3],
            process=Process.sequential,
            verbose=True
        )
        
        try:
            result3 = crew3.kickoff()
            # Extract full text from result
            if hasattr(result3, 'raw'):
                result3_str = str(result3.raw) if result3.raw else str(result3)
            elif hasattr(result3, 'content'):
                result3_str = str(result3.content) if result3.content else str(result3)
            elif hasattr(result3, '__str__'):
                result3_str = str(result3)
            else:
                result3_str = repr(result3) if result3 else "No result"
            print(f"\nValidacao completa:\n{result3_str}\n")
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            print(f"ERRO na Task 3: {error_msg}\n")
            print(f"   Tipo: {error_type}\n")
            result3 = "Error validating"
        
        # Save results (use full strings, not truncated)
        results.append({
            "file": file_key,
            "type": result1_str if 'result1_str' in locals() else str(result1),
            "columns": result2_str if 'result2_str' in locals() else str(result2),
            "validation": result3_str if 'result3_str' in locals() else str(result3)
        })
        
        print("="*70 + "\n")
    
    # Resumo final - UMA ÚNICA TABELA CONSOLIDADA
    print("\n" + "="*70)
    print("ANALISE COMPLETA!")
    print("="*70)
    print(f"\nArquivos processados: {len(results)}")
    
    # Mostrar tipos identificados
    print("\nTipos identificados:")
    for r in results:
        file_type = extract_file_type_from_result(r['type']) or 'Unknown'
        print(f"  - {r['file']}.csv: {file_type}")
    
    # Mostrar UMA ÚNICA TABELA CONSOLIDADA (com todas as colunas originais)
    # Rebuild all_analyses from results
    all_analyses_from_results = {}
    for r in results:
        if 'analysis' in r:
            all_analyses_from_results[r['file']] = r['analysis']
    print("\n" + format_consolidated_summary(results, all_analyses_from_results))
    print("\n" + "="*70 + "\n")
    
    return results, all_analyses_from_results


def run_analysis_api(data_dir):
    """API version - returns results without printing"""
    import sys
    from io import StringIO
    
    # Redirect stdout to capture prints
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    
    try:
        # Load heuristics
        heuristics = load_heuristics()
        
        # Create LLM instance
        llm_instance = create_llm()
        
        # Discover files
        files = {}
        for filename in os.listdir(data_dir):
            if filename.endswith('.csv'):
                file_key = filename[:-4]  # Remove .csv
                files[file_key] = os.path.join(data_dir, filename)
        
        if not files:
            return []
        
        # Create agents
        file_type_agent = create_file_type_agent(llm_instance)
        column_agent = create_column_identifier_agent(llm_instance)
        validator_agent = create_validator_agent(llm_instance)
        
        # First pass: Analyze all files
        all_analyses = {}
        for file_key, file_path in files.items():
            analysis = analyze_csv_structure(file_path)
            if "error" not in analysis:
                all_analyses[file_key] = analysis
        
        # Find common columns
        common_columns = {}
        if len(all_analyses) > 1:
            all_column_names = set()
            for analysis in all_analyses.values():
                all_column_names.update(analysis["columns"])
            
            for col_name in all_column_names:
                files_with_col = [f for f, a in all_analyses.items() if col_name in a["columns"]]
                if len(files_with_col) > 1:
                    common_columns[col_name] = {
                        "files": files_with_col,
                        "count": len(files_with_col)
                    }
        
        results = []
        
        # Process each file
        for file_key, file_path in files.items():
            analysis = analyze_csv_structure(file_path)
            if "error" in analysis:
                continue
            
            # TASK 1: Identify file type
            task1 = create_file_type_task(file_type_agent, analysis, heuristics)
            crew1 = Crew(
                agents=[file_type_agent],
                tasks=[task1],
                process=Process.sequential,
                verbose=False
            )
            
            try:
                result1 = crew1.kickoff()
                if hasattr(result1, 'raw'):
                    result1_str = str(result1.raw) if result1.raw else str(result1)
                elif hasattr(result1, 'content'):
                    result1_str = str(result1.content) if result1.content else str(result1)
                else:
                    result1_str = str(result1) if result1 else "No result"
            except Exception:
                result1_str = "Error identifying file type"
            
            # TASK 2: Identify columns
            file_type_str = result1_str
            task2 = create_column_identification_task(column_agent, analysis, file_type_str, heuristics, common_columns)
            crew2 = Crew(
                agents=[column_agent],
                tasks=[task2],
                process=Process.sequential,
                verbose=False
            )
            
            try:
                result2 = crew2.kickoff()
                if hasattr(result2, 'raw'):
                    result2_str = str(result2.raw) if result2.raw else str(result2)
                elif hasattr(result2, 'content'):
                    result2_str = str(result2.content) if result2.content else str(result2)
                else:
                    result2_str = str(result2)
                
                # Track token usage
                input_tokens = estimate_tokens(str(analysis) + str(file_type_str)) + 800  # Larger prompt
                output_tokens = estimate_tokens(result2_str)
                add_usage(input_tokens, output_tokens, model="gpt-3.5-turbo",
                         request_info={"file": file_key, "task": "column_identification"})
            except Exception:
                result2_str = "Error identifying columns"
            
            # TASK 3: Validate
            task3 = create_validation_task(validator_agent, result1, result2)
            crew3 = Crew(
                agents=[validator_agent],
                tasks=[task3],
                process=Process.sequential,
                verbose=False
            )
            
            try:
                result3 = crew3.kickoff()
                if hasattr(result3, 'raw'):
                    result3_str = str(result3.raw) if result3.raw else str(result3)
                elif hasattr(result3, 'content'):
                    result3_str = str(result3.content) if result3.content else str(result3)
                else:
                    result3_str = str(result3)
                
                # Track token usage
                input_tokens = estimate_tokens(str(result1_str) + str(result2_str)) + 200
                output_tokens = estimate_tokens(result3_str)
                add_usage(input_tokens, output_tokens, model="gpt-3.5-turbo",
                         request_info={"file": file_key, "task": "validation"})
            except Exception:
                result3_str = "Error validating"
            
            results.append({
                "file": file_key,
                "type": result1_str,
                "columns": result2_str,
                "validation": result3_str,
                "analysis": analysis
            })
        
        return results
    
    finally:
        sys.stdout = old_stdout


if __name__ == "__main__":
    run_analysis()

