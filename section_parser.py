import re
from typing import Dict, List, Tuple

def parse_manual_sections(manual_content: str) -> Dict[str, Dict]:
    """Parse the manual into structured sections"""
    
    lines = manual_content.split('\n')
    sections = {}
    current_section = None
    current_content = []
    
    # Section patterns
    main_section_pattern = r'^## (\d+)\s+(.+?)\s*\((\d+)\)$'  # ## 8 Storingen (55) - TOC format
    content_section_pattern = r'^# (\d+)\s+(.+)$'             # # 8 STORINGEN - actual content
    sub_section_pattern = r'^### (\d+\.\d+)\s+(.+)$'          # ### 8.1 Laatste storing
    subsection_pattern = r'^## (\d+\.\d+)\s+(.+)$'            # ## 8.1 Laatste storing tonen
    sub_sub_pattern = r'^#### (\d+\.\d+\.\d+)\s+(.+)$'        # #### 8.1.1 Something
    
    for i, line in enumerate(lines):
        # Check for main section (TOC format)
        main_match = re.match(main_section_pattern, line)
        content_match = re.match(content_section_pattern, line)
        
        if main_match or content_match:
            # Save previous section
            if current_section:
                sections[current_section['id']] = {
                    **current_section,
                    'content': '\n'.join(current_content).strip()
                }
            
            # Start new section
            if main_match:
                section_num = main_match.group(1)
                title = main_match.group(2)
                page = int(main_match.group(3))
                section_type = 'toc'
            else:  # content_match
                section_num = content_match.group(1)
                title = content_match.group(2)
                page = 0  # Will be updated if we find page reference
                section_type = 'content'
            
            # If we already have this section (from TOC), update it with content
            if section_num in sections and section_type == 'content':
                current_section = sections[section_num]
                current_section['type'] = 'content'
                current_content = [line]
            else:
                current_section = {
                    'id': section_num,
                    'title': title,
                    'page': page,
                    'type': section_type,
                    'full_title': f"# {section_num} {title}" if section_type == 'content' else f"## {section_num} {title}",
                    'subsections': []
                }
                current_content = [line]
            continue
        
        # Check for subsection
        sub_match = re.match(sub_section_pattern, line)
        subsection_match = re.match(subsection_pattern, line)
        if (sub_match or subsection_match) and current_section:
            if sub_match:
                subsection_num = sub_match.group(1)
                subsection_title = sub_match.group(2)
            else:
                subsection_num = subsection_match.group(1)
                subsection_title = subsection_match.group(2)
            
            current_section['subsections'].append({
                'id': subsection_num,
                'title': subsection_title,
                'line_start': i
            })
        
        # Add content to current section
        if current_section:
            current_content.append(line)
    
    # Save last section
    if current_section:
        sections[current_section['id']] = {
            **current_section,
            'content': '\n'.join(current_content).strip()
        }
    
    return sections

def get_section_by_question_type(question: str, sections: Dict) -> List[str]:
    """Intelligently map questions to relevant sections"""
    
    q_lower = question.lower()
    relevant_sections = []
    
    # Error codes and troubleshooting
    if any(word in q_lower for word in ['storing', 'error', 'code', 'fout', 'probleem']):
        if '8' in sections:
            relevant_sections.append('8')  # Storingen section
    
    # Water pressure, filling, venting
    if any(word in q_lower for word in ['waterdruk', 'druk', 'bar', 'vullen', 'bijvullen', 'ontluchten']):
        if '6' in sections:
            relevant_sections.append('6')  # In bedrijf stellen
    
    # Settings, parameters, adjustment
    if any(word in q_lower for word in ['parameter', 'instelling', 'instel', 'afregeling', 'servicecode']):
        if '7' in sections:
            relevant_sections.append('7')  # Instelling en afregeling
    
    # Maintenance
    if any(word in q_lower for word in ['onderhoud', 'reiniging', 'vervanging']):
        if '9' in sections:
            relevant_sections.append('9')  # Onderhoud
    
    # Technical specs
    if any(word in q_lower for word in ['technisch', 'specificatie', 'vermogen', 'afmeting']):
        if '10' in sections:
            relevant_sections.append('10')  # Technische specificaties
    
    # Installation
    if any(word in q_lower for word in ['installatie', 'aansluiting', 'montage']):
        if '4' in sections:
            relevant_sections.append('4')  # Installatie
        if '5' in sections:
            relevant_sections.append('5')  # Aansluiten
    
    # Description and operation
    if any(word in q_lower for word in ['werking', 'bedrijf', 'toestel', 'beschrijving', 'tapcomfort']):
        if '2' in sections:
            relevant_sections.append('2')  # Toestelomschrijving
    
    # Components
    if any(word in q_lower for word in ['component', 'onderdeel', 'sensor', 'klep', 'ventilator']):
        if '3' in sections:
            relevant_sections.append('3')  # Hoofdcomponenten
    
    # If no specific match, default to troubleshooting and description
    if not relevant_sections:
        if '8' in sections:
            relevant_sections.append('8')
        if '2' in sections:
            relevant_sections.append('2')
    
    return relevant_sections

def extract_storingscode_info(question: str, sections: Dict) -> str:
    """Specifically extract error code information"""
    
    # Look for error code numbers in question
    error_codes = re.findall(r'\b(\d+)\b', question)
    
    if not error_codes or '8' not in sections:
        return ""
    
    # Get the troubleshooting section
    section_8_content = sections['8']['content']
    
    # For each error code mentioned, try to find it in the troubleshooting section
    relevant_parts = []
    
    for code in error_codes:
        # Look for table entries with this error code
        lines = section_8_content.split('\n')
        for i, line in enumerate(lines):
            if f'<td>{code}</td>' in line:
                # Found error code, get context
                start = max(0, i - 3)
                end = min(len(lines), i + 10)
                context = '\n'.join(lines[start:end])
                relevant_parts.append(f"Storingscode {code}:\n{context}")
                break
    
    return '\n\n'.join(relevant_parts) if relevant_parts else section_8_content

def get_relevant_sections_smart(question: str, manual_content: str) -> str:
    """Smart section-based retrieval"""
    
    # Parse manual into sections
    sections = parse_manual_sections(manual_content)
    
    # Special handling for error codes
    if any(word in question.lower() for word in ['storing', 'error', 'code']) and re.search(r'\b\d+\b', question):
        error_info = extract_storingscode_info(question, sections)
        if error_info:
            return error_info
    
    # Get relevant section IDs
    relevant_section_ids = get_section_by_question_type(question, sections)
    
    # Combine relevant sections
    combined_content = []
    for section_id in relevant_section_ids:
        if section_id in sections:
            section = sections[section_id]
            combined_content.append(f"# {section['full_title']} (Pagina {section['page']})")
            combined_content.append(section['content'])
            combined_content.append("\n---\n")
    
    return '\n'.join(combined_content)