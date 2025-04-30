import os
from flask import Flask, request, jsonify, send_file, render_template
import yt_dlp
import tempfile
from threading import Thread, Lock
import uuid
import time

app = Flask(__name__)

# Storage for download status and files
download_status = {}
downloaded_files = {}
status_lock = Lock()

def get_ydl_options(format_type, download_id):
    """Return yt-dlp options with progress hook"""
    return {
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [lambda d: progress_hook(d, download_id)],
        'format': 'bestaudio/best' if format_type == 'audio' else 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }] if format_type == 'audio' else [],
        'outtmpl': os.path.join(tempfile.gettempdir(), f'dl_{download_id}.%(ext)s'),
    }

def progress_hook(d, download_id):
    with status_lock:
        if download_id not in download_status:
            download_status[download_id] = {'status': 'starting'}
        
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0%').replace('%', '')
            try:
                percent = float(percent)
            except:
                percent = 0
            
            download_status[download_id].update({
                'status': 'downloading',
                'progress': f"{percent:.1f}%",
                'speed': d.get('_speed_str', 'N/A'),
                'eta': d.get('_eta_str', 'N/A')
            })
        elif d['status'] == 'finished':
            download_status[download_id].update({
                'status': 'completed',
                'progress': '100%'
            })

def download_task(url, format_type, download_id):
    try:
        with status_lock:
            download_status[download_id] = {'status': 'starting', 'progress': '0%'}
        
        ydl_opts = get_ydl_options(format_type, download_id)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Get the actual downloaded file path
            if format_type == 'audio':
                filename = filename.rsplit('.', 1)[0] + '.mp3'
            
            with status_lock:
                downloaded_files[download_id] = {
                    'path': filename,
                    'ready': True,
                    'time': time.time(),
                    'filename': os.path.basename(filename)
                }
                
    except Exception as e:
        with status_lock:
            download_status[download_id] = {
                'status': 'error',
                'error': str(e)
            }

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url')
        format_type = request.form.get('format', 'video')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        download_id = str(uuid.uuid4())
        Thread(target=download_task, args=(url, format_type, download_id)).start()
        
        return jsonify({
            'status': 'started',
            'download_id': download_id
        })
    
    return render_template('index.html')

@app.route('/progress/<download_id>')
def check_progress(download_id):
    with status_lock:
        return jsonify(download_status.get(download_id, {'status': 'not found'}))

@app.route('/download/<download_id>')
def serve_file(download_id):
    with status_lock:
        if download_id not in downloaded_files or not downloaded_files[download_id]['ready']:
            return jsonify({'error': 'File not ready'}), 404
        
        file_info = downloaded_files.pop(download_id)
    
    try:
        response = send_file(
            file_info['path'],
            as_attachment=True,
            download_name=file_info['filename']
        )
        
        # Clean up after download
        def cleanup():
            try:
                if os.path.exists(file_info['path']):
                    os.remove(file_info['path'])
            except:
                pass
        
        response.call_on_close(cleanup)
        
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))