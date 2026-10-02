def split_into_paragraphs(text):
    split_text = text.split("\n\n")
    results = []
    for para in split_text:
        if para.split():
            results.append(para)

    return results

def split_long_paragraph(paragraph, chunk_limit):
    sentences = paragraph.split(".")
    chunks = []
    current_chunk = []
    current_word_count = 0 

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        sentence_word_count = len(sentence.split())
        
        if sentence_word_count > chunk_limit:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                
            split_words = sentence.split()
            start = 0
            while start < len(split_words):
                temp = split_words[start:chunk_limit+start]
                chunks.append(" ".join(temp))
                start += chunk_limit

            current_chunk = []
            current_word_count = 0
        else:
            if current_word_count + sentence_word_count <= chunk_limit:
                current_chunk.append(sentence)
                current_word_count += sentence_word_count
            else:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))

                current_chunk = [sentence]
                current_word_count = sentence_word_count

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def chunk_text(text, chunk_limit):
    paragraphs = split_into_paragraphs(text)
    
    chunks = []
    
    for paragraph in paragraphs:
        paragraph_length = len(paragraph.split())
        if paragraph_length <= chunk_limit:
            chunks.append(paragraph.strip())
        else:
            split_chunks = split_long_paragraph(paragraph, chunk_limit)
            
            chunks.extend(split_chunks)
            
    return chunks