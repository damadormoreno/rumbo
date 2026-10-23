# Rumbo en mi servidor Linux

Una sola copia de los datos, en el servidor, y acceso desde el móvil o el portátil con Tailscale.
Usa [`docker-compose.servidor.yml`](../docker-compose.servidor.yml), que construye la imagen desde
este fork y guarda los datos en la carpeta `mis_datos` junto al código.

## Lo que necesitas

- En el servidor: Git, Docker con el plugin `compose` y [Tailscale](https://tailscale.com).
- En el móvil y el portátil desde los que vayas a entrar: Tailscale, con la misma cuenta.

## 1. Sacar los datos del ordenador de Windows

1. **Cierra Rumbo** (la ventana negra) para que no guarde nada mientras copias.
2. En PowerShell, empaqueta la carpeta `mis_datos`. Incluye `.acceso`, tu llave, para que la dirección siga siendo la misma:

   ```powershell
   tar -czf "$HOME\mis_datos.tgz" -C D:\finanzas\rumbo-2.0.0 mis_datos
   ```

3. Pásala al servidor (cambia `usuario@servidor` por los tuyos):

   ```powershell
   scp "$HOME\mis_datos.tgz" usuario@servidor:~/
   ```

## 2. Arrancar Rumbo en el servidor

```bash
git clone -b deploy/servidor https://github.com/damadormoreno/rumbo.git ~/rumbo
cd ~/rumbo
tar -xzf ~/mis_datos.tgz            # crea ~/rumbo/mis_datos
sudo chown -R 1000:1000 mis_datos   # Rumbo corre como el usuario 1000 dentro del contenedor
docker compose -f docker-compose.servidor.yml up -d --build
docker compose -f docker-compose.servidor.yml logs rumbo
```

En los logs sale la dirección con la llave. La primera vez vuelve a descargar todos los precios: es normal.

Comprueba que están tus productos y tus perfiles. Cuando todo cuadre, borra `~/mis_datos.tgz` del servidor y
**deja de usar la instalación de Windows con datos reales**: si guardas en los dos sitios, tendrás dos carteras distintas.

## 3. Entrar desde fuera de casa

- Con Tailscale encendido en el servidor y en tu dispositivo, abre `http://<nombre-del-servidor>.<tu-tailnet>.ts.net:8765`
  con la llave que salió en los logs. Rumbo acepta los nombres `.ts.net` y las IP de Tailscale.
- **No abras el puerto 8765 en el router.** Rumbo no usa HTTPS: todo lo que viaje por internet sin VPN va en claro.
- Si prefieres un nombre propio (`rumbo.midominio.com`), descomenta `PATRIMONIO_HOSTS_PERMITIDOS` en el compose.

## 4. Actualizar

```bash
cd ~/rumbo
git pull
docker compose -f docker-compose.servidor.yml up -d --build
```

Los datos están fuera de la imagen: actualizar no los toca.

## 5. Copia de seguridad fuera del servidor

Las copias automáticas de Rumbo (`mis_datos/copias`) están en el mismo disco que los datos. Haz otra en otro sitio:
otro disco, otro equipo o la nube. Por ejemplo, cada noche a las 3 con `crontab -e`:

```cron
0 3 * * * tar -czf /ruta/a/otro/disco/rumbo_$(date +\%F).tgz -C $HOME/rumbo mis_datos
```

Para recuperar, para Rumbo (`docker compose -f docker-compose.servidor.yml down`), sustituye la carpeta
`mis_datos` por la de la copia, vuelve a poner el usuario 1000 (`sudo chown -R 1000:1000 mis_datos`) y arranca de nuevo.
