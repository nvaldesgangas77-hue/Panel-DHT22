from flask import Flask, render_template, jsonify, request, redirect, url_for, session, send_file
import serial, time, os, csv, pandas as pd
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

# ---------------- Configuración ----------------
PORT = "COM3"
BAUD = 9600
arduino = None

app = Flask(__name__)
app.secret_key = "supersecreto_nico"
app.permanent_session_lifetime = timedelta(minutes=15)

# ---------------- Base de datos usuarios ----------------
DB_USUARIOS = "usuarios.db"

def init_db():
    conn = sqlite3.connect(DB_USUARIOS)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT UNIQUE,
                    contrasena TEXT
                )""")
    conn.commit()
    c.execute("SELECT * FROM usuarios WHERE usuario=?", ("admin",))
    if not c.fetchone():
        c.execute("INSERT INTO usuarios (usuario, contrasena) VALUES (?, ?)",
                  ("admin", generate_password_hash("1234")))
        conn.commit()
        print("✅ Usuario admin creado (usuario: admin, contraseña: 1234)")
    conn.close()

init_db()

# ---------------- Conexión Arduino ----------------
def conectar_arduino():
    global arduino
    if arduino and arduino.is_open:
        return arduino
    try:
        arduino = serial.Serial(PORT, BAUD, timeout=2)
        time.sleep(2)
        print(f"✅ Conectado correctamente al puerto {PORT}")
        return arduino
    except Exception as e:
        print(f"⚠️ No se pudo conectar con Arduino: {e}")
        return None

arduino = conectar_arduino()

ultima_temp = 0.0
ultima_hum = 0.0

# ---------------- Guardar datos ----------------
def guardar_datos(temp, hum):
    fecha_actual = datetime.now()
    año = fecha_actual.strftime("%Y")
    mes = fecha_actual.strftime("%m_%B")
    dia = fecha_actual.strftime("%Y-%m-%d")

    carpeta_mes = os.path.join("data", año, mes)
    os.makedirs(carpeta_mes, exist_ok=True)
    archivo_csv = os.path.join(carpeta_mes, f"{dia}.csv")
    existe = os.path.exists(archivo_csv)

    with open(archivo_csv, "a", newline="") as f:
        writer = csv.writer(f)
        if not existe:
            writer.writerow(["Fecha", "Hora", "Temperatura (°C)", "Humedad (%)"])
        hora = fecha_actual.strftime("%H:%M:%S")
        writer.writerow([dia, hora, temp, hum])

# ---------------- Leer datos Arduino ----------------
def leer_datos():
    global ultima_temp, ultima_hum, arduino
    if not arduino or not arduino.is_open:
        arduino = conectar_arduino()
        return ultima_temp, ultima_hum

    try:
        linea = arduino.readline().decode(errors="ignore").strip()
        if linea:
            partes = linea.split(",")
            if len(partes) == 2:
                temp = float(partes[0])
                hum = float(partes[1])
                ultima_temp, ultima_hum = temp, hum
                guardar_datos(temp, hum)
                print(f"🌡️ {temp:.2f} °C | 💧 {hum:.2f} %")
                return temp, hum
    except Exception as e:
        print(f"⚠️ Error leyendo datos: {e}")
    return ultima_temp, ultima_hum

# ---------------- Funciones auxiliares ----------------
def limpiar_columnas(df):
    """Asegura que las columnas sean las esperadas."""
    posibles_temp = [c for c in df.columns if "Temp" in c]
    posibles_hum = [c for c in df.columns if "Hum" in c]
    if posibles_temp and posibles_hum:
        df["Temperatura (°C)"] = pd.to_numeric(df[posibles_temp[0]], errors="coerce")
        df["Humedad (%)"] = pd.to_numeric(df[posibles_hum[0]], errors="coerce")
    return df.dropna(subset=["Temperatura (°C)", "Humedad (%)"])

# ---------------- Rutas protegidas ----------------
def login_requerido(func):
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

@app.route("/")
@login_requerido
def index():
    return render_template("index.html", usuario=session["usuario"])

@app.route("/data")
@login_requerido
def data():
    temp, hum = leer_datos()
    return jsonify({"temperatura": temp, "humedad": hum})

# ---------------- Histórico ----------------
@app.route("/historico_data")
@login_requerido
def historico_data():
    return procesar_historico_por_fecha(datetime.now().strftime("%Y-%m-%d"))

@app.route("/historico_por_fecha/<fecha>")
@login_requerido
def historico_por_fecha(fecha):
    return procesar_historico_por_fecha(fecha)

def procesar_historico_por_fecha(fecha):
    try:
        ruta = None
        for root, _, files in os.walk("data"):
            for f in files:
                if f.endswith(f"{fecha}.csv"):
                    ruta = os.path.join(root, f)
        if not ruta:
            return jsonify({"error": "No hay datos disponibles"})

        # Intentar leer el archivo con varias codificaciones
        for cod in ["utf-8", "latin1", "iso-8859-1"]:
            try:
                df = pd.read_csv(ruta, encoding=cod)
                break
            except Exception:
                continue

        df = limpiar_columnas(df)
        if df.empty:
            return jsonify({"error": "No hay datos válidos"})

        df["Hora"] = pd.to_datetime(df["Hora"], errors="coerce")
        df = df.dropna(subset=["Hora"])
        df["Hora_str"] = df["Hora"].dt.strftime("%H:%M")

        temp_prom = df.groupby("Hora_str")["Temperatura (°C)"].mean().round(2).tolist()
        hum_prom = df.groupby("Hora_str")["Humedad (%)"].mean().round(2).tolist()
        horas = df["Hora_str"].unique().tolist()

        return jsonify({
            "fechas": horas,
            "temp_mean": temp_prom,
            "hum_mean": hum_prom
        })
    except Exception as e:
        print(f"❌ Error procesando histórico: {e}")
        return jsonify({"error": str(e)})

# ---------------- Valores extremos globales ----------------
@app.route("/extremos")
@login_requerido
def extremos():
    try:
        temps, hums = [], []
        for root, _, files in os.walk("data"):
            for f in files:
                if f.endswith(".csv"):
                    ruta = os.path.join(root, f)
                    try:
                        # Intentar leer con varias codificaciones
                        for cod in ["utf-8", "latin1", "iso-8859-1"]:
                            try:
                                df = pd.read_csv(ruta, encoding=cod)
                                break
                            except Exception:
                                continue

                        df = limpiar_columnas(df)
                        temps.extend(df["Temperatura (°C)"].dropna().tolist())
                        hums.extend(df["Humedad (%)"].dropna().tolist())
                    except Exception:
                        continue

        if not temps or not hums:
            return jsonify({"error": "No hay datos para calcular extremos"})

        temp_series = pd.Series(temps)
        hum_series = pd.Series(hums)
        return jsonify({
            "temp_max": float(temp_series.max()),
            "temp_min": float(temp_series.min()),
            "temp_mean": float(temp_series.mean()),
            "temp_std": float(temp_series.std()),
            "hum_max": float(hum_series.max()),
            "hum_min": float(hum_series.min()),
            "hum_mean": float(hum_series.mean()),
            "hum_std": float(hum_series.std())
        })
    except Exception as e:
        print(f"❌ Error procesando extremos: {e}")
        return jsonify({"error": str(e)})

# ---------------- Login / Logout ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        contrasena = request.form["contrasena"]
        conn = sqlite3.connect(DB_USUARIOS)
        c = conn.cursor()
        c.execute("SELECT contrasena FROM usuarios WHERE usuario=?", (usuario,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[0], contrasena):
            session["usuario"] = usuario
            session.permanent = True
            return redirect(url_for("index"))
        else:
            return render_template("login.html", error="Credenciales incorrectas")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))

# ---------------- Ejecución ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
