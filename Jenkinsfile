pipeline {
    agent any
    stages {
        stage('Deploy on minipc') {
            steps {
                sh """
                ssh minipc '
                    cd /home/suchokrates1/retrievershop-suite &&
                    git pull &&
                    docker compose up -d --build
                '
                """
            }
        }
    }
}
