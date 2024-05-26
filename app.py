import streamlit as st
import os
import requests
from openai import OpenAI
from dotenv import load_dotenv
import mysql.connector
import speech_recognition as sr
import pygame
from time import sleep
from pathlib import Path
from bs4 import BeautifulSoup

# Carica la chiave API e le credenziali del database dal file .env
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
db_host = os.getenv("DB_HOST")
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME")

# Verifica che le credenziali siano caricate correttamente
if not api_key:
    st.error("La chiave API non è stata trovata. Assicurati di averla impostata correttamente nel file .env.")
    st.stop()
if not db_host or not db_user or db_password is None or not db_name:
    st.error("Le credenziali del database non sono state trovate. Assicurati di averle impostate correttamente nel file .env.")
    st.stop()

# Crea il client OpenAI
client = OpenAI(api_key=api_key)

# Leggi lo schema del database dal file schema.txt
schema_file = "schema.txt"
if not os.path.exists(schema_file):
    st.error(f"Il file {schema_file} non è stato trovato. Assicurati che sia presente nella stessa cartella del file Python.")
    st.stop()

with open(schema_file, 'r', encoding='utf-8') as file:
    database_schema = file.read()

# Leggi i nomi delle immagini disponibili nella cartella "img"
img_dir = Path("img")
available_images = {}
image_base_url = "https://www.justwebsite.it/img"
if img_dir.exists() and img_dir.is_dir():
    for img_file in img_dir.iterdir():
        if img_file.suffix in [".jpg", ".png", ".jpeg"]:
            available_images[img_file.stem] = img_file.name

def natural_language_to_sql(natural_language_query):
    prompt = f"Il seguente è lo schema del database:\n\n{database_schema}\n\nConverti la seguente richiesta in linguaggio naturale in una query SQL:\n\n{natural_language_query}"
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant. You will generate only code and won't write anything else. Make more than one query (only if needed) and try to make them generically using, for example, LIKE variable=%search name%. Always limit to 10 the numbers of results"},
            {"role": "user", "content": prompt}
        ]
    )
    sql_query = response.choices[0].message.content.strip()
    sql_query = sql_query.replace("```sql", "").replace("```", "").strip()  # Rimuovi i delimitatori di blocco markdown
    return sql_query

def execute_query(query):
    try:
        conn_params = {
            'host': db_host,
            'user': db_user,
            'password': db_password,
            'database': db_name
        }
        
        if not db_password:
            conn_params.pop('password')

        conn = mysql.connector.connect(**conn_params)
        cursor = conn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        cursor.close()
        conn.close()
        return result
    except mysql.connector.Error as err:
        return f"Errore: {err}"

def generate_response(natural_language_query, query_result):
    image_context = "\n".join(f"- {image}: {image_base_url}/{available_images[image]}" for image in available_images)
    prompt = (
        f"La seguente domanda è stata fatta in linguaggio naturale:\n\n{natural_language_query}\n\n"
        f"Questo è il risultato della query eseguita sul database:\n\n{query_result}\n\n"
        f"Le seguenti immagini sono disponibili:\n\n{image_context}\n\n"
        f"Rispondi alla domanda utilizzando il risultato della query e includendo direttamente i tag <img> con le immagini pertinenti nel testo della risposta. "
        f"Utilizza il formato <img src='{image_base_url}/image_name.extension' alt='image_name' width='300'> dove devono essere posizionate le immagini. "
        f"Genera una risposta in HTML ben strutturata e visivamente accattivante. Non racchiudere la risposta nei blocchi di codice markdown."
    )
    # Aggiungi il contesto della chat
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    if "chat_history" in st.session_state:
        messages += st.session_state.chat_history
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    answer = response.choices[0].message.content.strip()
    
    # Rimuovi tutti i blocchi di codice markdown
    answer = answer.replace("```html", "").replace("```", "").strip()
    
    # Aggiungi la risposta alla storia della chat
    st.session_state.chat_history.append({"role": "user", "content": natural_language_query})
    st.session_state.chat_history.append({"role": "assistant", "content": answer})
    
    # Log la risposta
    print("Risposta generata dal modello:", answer)
    
    return answer

def get_voice_input():
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()
    with microphone as source:
        st.write("Parla ora, sto ascoltando...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)
    try:
        st.write("Riconoscimento in corso...")
        return recognizer.recognize_google(audio, language="it-IT")
    except sr.UnknownValueError:
        return "Non sono riuscito a capire l'audio"
    except sr.RequestError:
        return "Errore durante la richiesta di riconoscimento vocale"

def speak_text(text):
    speech_file_path = "response.mp3"
    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "tts-1",
        "voice": "alloy",
        "input": text
    }

    try:
        if os.path.exists(speech_file_path):
            os.remove(speech_file_path)

        response = requests.post(url, headers=headers, json=data, stream=True)
        response.raise_for_status()

        with open(speech_file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        if os.path.exists(speech_file_path):
            pygame.mixer.init()
            pygame.mixer.music.load(speech_file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                sleep(1)
        else:
            st.write("Errore: il file audio non è stato creato correttamente.")
    except Exception as e:
        st.error(f"Errore durante la generazione o riproduzione dell'audio: {str(e)}")

def filter_html_tags(text):
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text()

# Inizializza lo stato della sessione
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Interfaccia Streamlit
st.title("Chat vocale e testuale con OpenAI")

mode = st.radio("Scegli il metodo di input:", ('Testo', 'Voce'))

if mode == 'Testo':
    user_query = st.text_input("Inserisci la tua richiesta in linguaggio naturale:")
    if st.button("Invia"):
        if user_query:
            sql_query = natural_language_to_sql(user_query)
            print("Query SQL generata:", sql_query)  # Log della query SQL
            result = execute_query(sql_query)
            print("Risultato della query:", result)  # Log del risultato della query
            response = generate_response(user_query, result)
            print("Risposta generata dal modello:", response)  # Log della risposta generata
            st.markdown(response, unsafe_allow_html=True)
            voice_text = filter_html_tags(response)
            speak_text(voice_text)
        else:
            st.write("Per favore, inserisci una richiesta.")
else:
    if st.button("Registra"):
        user_query = get_voice_input()
        print(f"Richiesta riconosciuta: {user_query}")
        sql_query = natural_language_to_sql(user_query)
        print("Query SQL generata:", sql_query)  # Log della query SQL
        result = execute_query(sql_query)
        print("Risultato della query:", result)  # Log del risultato della query
        response = generate_response(user_query, result)
        print("Risposta generata dal modello:", response)  # Log della risposta generata
        st.markdown(response, unsafe_allow_html=True)
        voice_text = filter_html_tags(response)
        speak_text(voice_text)

# Visualizza la storia della chat
st.write("### Storia della Chat")
for message in st.session_state.chat_history:
    if message["role"] == "user":
        st.write(f"**Utente:** {message['content']}")
    elif message["role"] == "assistant":
        st.markdown(message["content"], unsafe_allow_html=True)
