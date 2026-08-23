"""Importador de tarjetas de cámara.

Paquete deliberadamente independiente de Flask y del resto de `converter/`: toda la
lógica vive aquí en funciones puras o jobs con hilos, para poder extraerlo tal cual
a una aplicación propia en el futuro sin arrastrar el conversor de vídeo.
"""
