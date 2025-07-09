pipeline {
    agent any
    stages {
        stage('Deploy on RPi5') {
            steps {
                sh """
                ssh suchokrates1@192.168.1.107 '
                    cd /home/suchokrates1/retrievershop-suite &&
                    git pull &&
                    docker compose down || true &&
                    docker compose up -d --build
                '
                """
            }
        }
    }
}
