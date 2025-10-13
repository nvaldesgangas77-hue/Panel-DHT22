#include "DHT.h"

#define DHTPIN D2       // Pin donde está conectado el DHT22
#define DHTTYPE DHT22  // Tipo de sensor

DHT dht(DHTPIN, DHTTYPE);

void setup() {
  Serial.begin(9600);
  dht.begin();
}

void loop() {
  float h = dht.readHumidity();
  float t = dht.readTemperature(); // Celsius por defecto

  if (isnan(h) || isnan(t)) {
    Serial.println("Error al leer DHT22");
    return;
  }

  // Envía los datos separados por coma (ej: 24.50,58.00)
  Serial.print(t);
  Serial.print(",");
  Serial.println(h);

  delay(2000); // Actualiza cada 1 segundo
}
